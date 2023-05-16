import csv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Load the CSV file with the song list
with open("FILENAME", "r") as csvfile:
    reader = csv.reader(csvfile)
    next(reader)  # skip the header row
    songs = [(row[0], row[1]) for row in reader]

# Authenticate with the Spotify API
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id="CLIENT_ID", client_secret="CLIENT_SECRET", redirect_uri="REDIRECT_URL", scope="playlist-modify-public"))

# Create a new playlist and add the songs
playlist_name = "NAME OF PLAYLIST"
playlist = sp.user_playlist_create(sp.current_user()["id"], playlist_name)

for song, artist in songs:
    query = f"{song} {artist}"
    results = sp.search(q=query, type="track")
    if results["tracks"]["items"]:
        track = results["tracks"]["items"][0]
        sp.playlist_add_items(playlist["id"], [track["id"]])

print("Playlist created: " + playlist["external_urls"]["spotify"])
