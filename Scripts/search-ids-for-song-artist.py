import csv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Set up your variables
client_id = 'ID'
client_secret = 'SECRET'
input = 'FILENAME'
output = 'FILENAME'

# Create a Spotify client
client_credentials_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
spotify = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

def get_song_info(spotify_ids):
    song_info = []
    for id in spotify_ids:
        track = spotify.track(id)
        song_title = track['name']
        artists = ', '.join([artist['name'] for artist in track['artists']])
        song_info.append({'spotify_id': id, 'title': song_title, 'artists': artists})
    return song_info

# Read Spotify IDs from a CSV file
csv_file_path = input
spotify_ids = []
with open(csv_file_path, 'r') as file:
    csv_reader = csv.reader(file)
    next(csv_reader)  # Skip header row if it exists
    for row in csv_reader:
        spotify_ids.append(row[0])

# Get song information for Spotify IDs
song_info = get_song_info(spotify_ids)

# Output song information to a CSV file
output_csv_file_path = 'FILE'
with open(output_csv_file_path, 'w', newline='') as file:
    fieldnames = ['Spotify ID', 'Title', 'Artists']
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    writer.writeheader()
    for info in song_info:
        writer.writerow({'Spotify ID': info['spotify_id'], 'Title': info['title'], 'Artists': info['artists']})

print(f"Song information has been written to {output_csv_file_path}.")
