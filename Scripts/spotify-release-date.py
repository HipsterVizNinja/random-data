import csv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Set up Spotipy client
client_credentials_manager = SpotifyClientCredentials(client_id='CLIENT_ID', client_secret='CLIENT_SECRET')
sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# Set up input and output files
input_file = 'FILE'
output_file = 'FILE'

# Read input CSV file
with open(input_file, newline='', encoding='utf-8') as csvfile:
    reader = csv.reader(csvfile)
    # Skip header row
    next(reader)
    # Iterate over rows
    for row in reader:
        # Extract song title and artist name from row
        song_title = row[1]
        artist_name = row[0]
        # Search for track on Spotify
        results = sp.search(q='track:' + song_title + ' artist:' + artist_name, type='track', limit=1)
        # Extract release date from results
        try:
            track_id = results['tracks']['items'][0]['id']
            release_date = results['tracks']['items'][0]['album']['release_date']
        except IndexError:
            track_id = 'Not found'
            release_date = 'Not found'
        # Add release date to row
        row.append(track_id)
        row.append(release_date)

        # Append row to output CSV file
        with open(output_file, 'a', newline='', encoding='utf-8') as outfile:
            writer = csv.writer(outfile)
            writer.writerow(row)
