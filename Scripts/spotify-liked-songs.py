#!/usr/bin/env python3
"""Export every song in your Spotify "Liked Songs" library to a CSV.

Setup (one time):
  1. Create an app at https://developer.spotify.com/dashboard
     - Redirect URI: http://127.0.0.1:8888/callback  (Spotify no longer accepts "localhost")
     - APIs used: Web API
  2. Paste the app's client id into spotify.env next to this script (gitignored):
       SPOTIFY_CLIENT_ID=<your app's client id>
     or export SPOTIFY_CLIENT_ID in your shell, which takes precedence.

Run:
  python3 spotify-liked-songs.py                # writes liked-songs-YYYY-MM-DD.csv
  python3 spotify-liked-songs.py -o my.csv

Uses the Authorization Code + PKCE flow, so no client secret is needed. A browser
window opens for you to log in; the script catches the redirect on 127.0.0.1:8888.

Audio features (danceability, energy, tempo, ...) come from ReccoBeats because
Spotify's own endpoint is closed to new apps. audio_features_match says whether a
song matched by track_id or isrc; it's blank when ReccoBeats has no data for it.
"""
import argparse
import base64
import csv
import datetime
import hashlib
import http.server
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser

import requests

AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
API_URL = 'https://api.spotify.com/v1'
REDIRECT_URI = 'http://127.0.0.1:8888/callback'
SCOPE = 'user-library-read'
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spotify.env')

# Spotify's /audio-features returns 403 for apps created after 2024-11-27, so audio
# features come from ReccoBeats (free, no key), which accepts Spotify track IDs.
RECCOBEATS_URL = 'https://api.reccobeats.com/v1/audio-features'
RECCOBEATS_BATCH = 40  # API max ids per request
AUDIO_FEATURES = [
    'danceability', 'energy', 'key', 'loudness', 'mode', 'speechiness',
    'acousticness', 'instrumentalness', 'liveness', 'valence', 'tempo',
]

COLUMNS = [
    'added_at', 'track_name', 'artists', 'album', 'album_artists', 'release_date',
    'album_type', 'disc_number', 'track_number', 'duration_ms', 'explicit', 'isrc',
    'is_local', 'track_id', 'artist_ids', 'album_id', 'spotify_url',
] + AUDIO_FEATURES + ['audio_features_match']


def get_auth_code(client_id, code_challenge, state):
    """Open the Spotify login page and wait for the redirect carrying the auth code."""
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h3>Spotify login complete. You can close this tab.</h3>')

        def log_message(self, *args):
            pass

    params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPE,
        'state': state,
        'code_challenge_method': 'S256',
        'code_challenge': code_challenge,
    }
    url = AUTH_URL + '?' + urllib.parse.urlencode(params)

    redirect = urllib.parse.urlparse(REDIRECT_URI)
    server = http.server.HTTPServer((redirect.hostname, redirect.port), Handler)
    print('Opening browser for Spotify login. If it does not open, visit:\n' + url)
    webbrowser.open(url)
    while 'code' not in result and 'error' not in result:
        server.handle_request()
    server.server_close()

    if 'error' in result:
        sys.exit(f"Spotify login failed: {result['error']}")
    if result.get('state') != state:
        sys.exit('Spotify login failed: state mismatch')
    return result['code']


def get_access_token(client_id):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    code = get_auth_code(client_id, challenge, secrets.token_urlsafe(16))

    response = requests.post(TOKEN_URL, data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': client_id,
        'code_verifier': verifier,
    })
    response.raise_for_status()
    return response.json()['access_token']


def get_liked_songs(token):
    """Page through /me/tracks (50 per page, the API max), honoring rate limits."""
    headers = {'Authorization': f'Bearer {token}'}
    url = f'{API_URL}/me/tracks?limit=50'
    items = []
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code == 429:
            time.sleep(int(response.headers.get('Retry-After', 5)))
            continue
        response.raise_for_status()
        page = response.json()
        items.extend(page['items'])
        print(f"Fetched {len(items)} of {page['total']}")
        url = page['next']
    return items


def fetch_reccobeats(ids):
    """Query ReccoBeats audio features in batches; ids may be Spotify track IDs or ISRCs."""
    results = []
    for start in range(0, len(ids), RECCOBEATS_BATCH):
        batch = ids[start:start + RECCOBEATS_BATCH]
        while True:
            response = requests.get(RECCOBEATS_URL, params={'ids': ','.join(batch)})
            if response.status_code != 429:
                break
            time.sleep(int(response.headers.get('Retry-After', 5)))
        response.raise_for_status()
        results.extend(response.json()['content'])
    return results


def add_audio_features(rows):
    """Match by Spotify track ID first, then by ISRC, since Spotify often lists the same
    recording under several track IDs (album, single, compilation) and ReccoBeats may
    only know one of them. Songs found by neither are left blank."""
    by_track = {}
    for f in fetch_reccobeats([r['track_id'] for r in rows if r['track_id']]):
        # ReccoBeats' own id is a UUID; the Spotify track ID is the end of href
        by_track[f['href'].rstrip('/').split('/')[-1]] = f

    missing_isrcs = [r['isrc'] for r in rows if r['track_id'] not in by_track and r['isrc']]
    by_isrc = {}
    for f in fetch_reccobeats(list(dict.fromkeys(missing_isrcs))):
        by_isrc.setdefault(f['isrc'], f)  # several releases can share an ISRC; keep the first

    for row in rows:
        if row['track_id'] in by_track:
            f, source = by_track[row['track_id']], 'track_id'
        elif row['isrc'] in by_isrc:
            f, source = by_isrc[row['isrc']], 'isrc'
        else:
            f, source = {}, None
        row.update({name: f.get(name) for name in AUDIO_FEATURES})
        row['audio_features_match'] = source

    found = sum(1 for r in rows if r['audio_features_match'])
    print(f'Audio features: {found} of {len(rows)} songs '
          f'({len(by_track)} by track ID, {found - len(by_track)} by ISRC)')


def to_row(item):
    track = item['track']
    album = track.get('album') or {}
    artists = track.get('artists') or []
    return {
        'added_at': item['added_at'],
        'track_name': track.get('name'),
        'artists': '; '.join(a['name'] for a in artists),
        'album': album.get('name'),
        'album_artists': '; '.join(a['name'] for a in album.get('artists') or []),
        'release_date': album.get('release_date'),
        'album_type': album.get('album_type'),
        'disc_number': track.get('disc_number'),
        'track_number': track.get('track_number'),
        'duration_ms': track.get('duration_ms'),
        'explicit': track.get('explicit'),
        'isrc': (track.get('external_ids') or {}).get('isrc'),
        'is_local': track.get('is_local'),
        'track_id': track.get('id'),
        'artist_ids': '; '.join(a['id'] for a in artists if a.get('id')),
        'album_id': album.get('id'),
        'spotify_url': (track.get('external_urls') or {}).get('spotify'),
    }


def load_env_file(path):
    """Read KEY=value lines from a gitignored credentials file; real env vars take precedence."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def main():
    parser = argparse.ArgumentParser(description='Export Spotify Liked Songs to CSV')
    parser.add_argument('-o', '--output', default=f'liked-songs-{datetime.date.today()}.csv')
    args = parser.parse_args()

    load_env_file(ENV_FILE)
    client_id = os.environ.get('SPOTIFY_CLIENT_ID')
    if not client_id:
        sys.exit(f'Paste your Spotify app client id into {ENV_FILE} (see the docstring for setup).')

    token = get_access_token(client_id)
    rows = [to_row(item) for item in get_liked_songs(token) if item.get('track')]
    add_audio_features(rows)

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f'Wrote {len(rows)} liked songs to {args.output}')


if __name__ == '__main__':
    main()
