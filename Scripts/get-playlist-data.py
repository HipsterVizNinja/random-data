import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd

cid = 'YOUR SPOTIFY CLIENT ID'
secret = 'YOUR SPOTIFY SECRET'

client_credentials_manager = SpotifyClientCredentials(client_id=cid, client_secret=secret)

sp = spotipy.Spotify(client_credentials_manager = client_credentials_manager)

# Set settings for dataframe
pd.set_option('display.max_rows', 1000)
pd.options.display.max_colwidth = 150
pd.set_option('display.max_columns', None)

# Function to extract MetaData from a playlist thats longer than 100 songs
def get_playlist_tracks_more_than_100_songs(username, playlist_id):
    results = sp.user_playlist_tracks(username,playlist_id)
    tracks = results['items']
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])
    results = tracks

    playlist_tracks_id = []
    playlist_tracks_titles = []
    playlist_tracks_artists = []
    playlist_tracks_first_artists = []
    playlist_tracks_first_release_date = []
    playlist_tracks_popularity = []
    playlist_tracks_explicit = []

    for i in range(len(results)):
        print(i) # Counter
        if i == 0:
            playlist_tracks_id = results[i]['track']['id']
            playlist_tracks_titles = results[i]['track']['name']
            playlist_tracks_first_release_date = results[i]['track']['album']['release_date']
            playlist_tracks_popularity = results[i]['track']['popularity']
            playlist_tracks_explicit = results[i]['track']['explicit']
            artist_list = []
            for artist in results[i]['track']['artists']:
                artist_list= artist['name']
            playlist_tracks_artists = artist_list

            features = sp.audio_features(playlist_tracks_id)
            features_df = pd.DataFrame(data=features, columns=features[0].keys())
            features_df['title'] = playlist_tracks_titles
            features_df['all_artists'] = playlist_tracks_artists
            features_df['popularity'] = playlist_tracks_popularity
            features_df['explicit'] = playlist_tracks_explicit
            features_df['release_date'] = playlist_tracks_first_release_date
            features_df = features_df[['id', 'title', 'all_artists', 'popularity', 'release_date', 'explicit',
                                       'danceability', 'energy', 'key', 'loudness',
                                       'mode', 'acousticness', 'instrumentalness',
                                       'liveness', 'valence', 'tempo',
                                       'duration_ms', 'time_signature']]
            continue
        else:
            try:
                playlist_tracks_id = results[i]['track']['id']
                playlist_tracks_titles = results[i]['track']['name']
                playlist_tracks_first_release_date = results[i]['track']['album']['release_date']
                playlist_tracks_popularity = results[i]['track']['popularity']
                playlist_tracks_explicit = results[i]['track']['explicit']
                artist_list = []
                for artist in results[i]['track']['artists']:
                    artist_list= artist['name']
                playlist_tracks_artists = artist_list
                features = sp.audio_features(playlist_tracks_id)
                new_row = {'id':[playlist_tracks_id],
                           'title':[playlist_tracks_titles],
                           'all_artists':[playlist_tracks_artists],
                           'popularity':[playlist_tracks_popularity],
                           'release_date':[playlist_tracks_first_release_date],
                           'explicit':[playlist_tracks_explicit],
                           'danceability':[features[0]['danceability']],
                           'energy':[features[0]['energy']],
                           'key':[features[0]['key']],
                           'loudness':[features[0]['loudness']],
                           'mode':[features[0]['mode']],
                           'acousticness':[features[0]['acousticness']],
                           'instrumentalness':[features[0]['instrumentalness']],
                           'liveness':[features[0]['liveness']],
                           'valence':[features[0]['valence']],
                           'tempo':[features[0]['tempo']],
                           'duration_ms':[features[0]['duration_ms']],
                           'time_signature':[features[0]['time_signature']]
                           }

                dfs = [features_df, pd.DataFrame(new_row)]
                features_df = pd.concat(dfs, ignore_index = True)
            except:
                continue

    return features_df

y=get_playlist_tracks_more_than_100_songs('SPOTIFY PLAYLIST OWNER USERNAME', 'SPOTIFY PLAYLIST ID')
y.to_csv('OUTPUT PATH')
print(y)
