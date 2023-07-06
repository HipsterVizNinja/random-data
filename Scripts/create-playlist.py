import csv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Set up your variables
client_id = 'ID'
client_secret = 'SECRET'
redirect = 'URL'
input = 'FILENAME'
playlist_name = 'NAME'
description = 'DESCRIPTION'

# # Authenticate with the Spotify API
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect, scope="playlist-modify-public"))

# Set up input CSV file
input_file = input

# Read CSV file
with open(input_file, newline='', encoding='utf-8') as csvfile:
    reader = csv.reader(csvfile)
    # Skip header row
    next(reader)
    # Extract track IDs from CSV
    track_ids = [row[0] for row in reader]

# Create a new playlist
playlist_name = playlist_name
playlist_description = description
user_id = sp.me()['id']
playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=True, description=playlist_description)

# Add tracks to the playlist in batches
batch_size = 100
for i in range(0, len(track_ids), batch_size):
    batch = track_ids[i:i + batch_size]
    sp.user_playlist_add_tracks(user=user_id, playlist_id=playlist['id'], tracks=batch)
    
print("Playlist created successfully!")






