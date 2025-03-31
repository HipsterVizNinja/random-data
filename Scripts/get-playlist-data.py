import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd

cid = 'b8d3901151d34489a160e3cf0ab1fa94'
secret = 'a9600e00b0d24812ac8eb1e610ca5021'
user_id = 'mskm203'
playlist_link = 'https://open.spotify.com/playlist/00dsmqdA8Zu6lSLdJG3T1D?si=3c0ef326e8ab418d'
output = '2021-08-06'

playlist_uri = playlist_link.split('/')[-1].split('?')[0]

client_credentials_manager = SpotifyClientCredentials(client_id=cid, client_secret=secret)

sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# Set settings for the dataframe
pd.set_option('display.max_rows', 1000)
pd.options.display.max_colwidth = 150
pd.set_option('display.max_columns', None)

# Function to extract MetaData from a playlist that's longer than 100 songs
def get_playlist_tracks_more_than_100_songs(user, playlist_id):
    results = sp.user_playlist_tracks(user, playlist_id)
    tracks = results['items']
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])
    results = tracks

    data = {
        'id': [],
        'title': [],
        'album': [],
        'all_artists': [],
        'artist_tags': [],
        'popularity': [],
        'release_date': [],
        'explicit': [],
        'danceability': [],
        'energy': [],
        'key': [],
        'loudness': [],
        'mode': [],
        'acousticness': [],
        'instrumentalness': [],
        'liveness': [],
        'valence': [],
        'tempo': [],
        'duration_ms': [],
        'time_signature': [],
    }

    for i in range(len(results)):
        print(i)  # Counter
        try:
            playlist_tracks_id = results[i]['track']['id']
            playlist_tracks_titles = results[i]['track']['name']
            playlist_tracks_albums = results[i]['track']['album']['name']  # Retrieve the album title
            playlist_tracks_first_release_date = results[i]['track']['album']['release_date']
            playlist_tracks_popularity = results[i]['track']['popularity']
            playlist_tracks_explicit = results[i]['track']['explicit']
            artist_list = []
            artist_tags_list = []  # New list to store artist tags
            for artist in results[i]['track']['artists']:
                artist_list.append(artist['name'])  # Append each artist to the list
                # Retrieve artist information to get genres (tags)
                artist_info = sp.artist(artist['id'])
                artist_tags_list.extend(artist_info.get('genres', [])) 
            playlist_tracks_artists = artist_list
            playlist_tracks_artist_tags = artist_tags_list

            features = sp.audio_features(playlist_tracks_id)

            data['id'].append(playlist_tracks_id)
            data['title'].append(playlist_tracks_titles)
            data['album'].append(playlist_tracks_albums)
            data['all_artists'].append(playlist_tracks_artists)
            data['artist_tags'].append(playlist_tracks_artist_tags)
            data['popularity'].append(playlist_tracks_popularity)
            data['release_date'].append(playlist_tracks_first_release_date)
            data['explicit'].append(playlist_tracks_explicit)
            data['danceability'].append(features[0]['danceability'])
            data['energy'].append(features[0]['energy'])
            data['key'].append(features[0]['key'])
            data['loudness'].append(features[0]['loudness'])
            data['mode'].append(features[0]['mode'])
            data['acousticness'].append(features[0]['acousticness'])
            data['instrumentalness'].append(features[0]['instrumentalness'])
            data['liveness'].append(features[0]['liveness'])
            data['valence'].append(features[0]['valence'])
            data['tempo'].append(features[0]['tempo'])
            data['duration_ms'].append(features[0]['duration_ms'])
            data['time_signature'].append(features[0]['time_signature'])

        except:
            continue

    features_df = pd.DataFrame(data)

    # Remove square brackets from all columns
    features_df = features_df.applymap(lambda x: str(x).replace('[', '').replace(']', ''))

    return features_df

y = get_playlist_tracks_more_than_100_songs(user_id, playlist_uri)
y.to_csv('/Users/sean_miller/Library/CloudStorage/OneDrive-Concord/Documents/Code/random-data/Music/Spotify/Discover-Weekly/' + output + '.csv')
print(y)
