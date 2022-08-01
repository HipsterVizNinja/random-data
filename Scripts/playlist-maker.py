import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.oauth2 import SpotifyClientCredentials
import json

# Connect to Spotify - Create a web app at https://developer.spotify.com/dashboard/. Then paste client id & secret below
spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id='b8d3901151d34489a160e3cf0ab1fa94',client_secret='a9600e00b0d24812ac8eb1e610ca5021'))

scope = 'playlist-modify-public'
username = 'mskm'

token = SpotifyOAuth(spotipy, scope=scope, username=username)

playlist_name = input('Name of playlist: ')
playlist_description = input('Description of Playlist')

# print(json.dumps(newResults,sort_keys=True, indent=4))

spotify.user_playlist_create(user=username, name=playlist_name, public=True, description=playlist_description)

user_input = ''
user_input = input('enter song name: ')
list_of_songs = []
while user_input != 'quit':
    results = spotify.search(q=user_input)
    print(results['tracks']['items'][0]['uri'])

    newResults = results['tracks']['items'][0]['uri']

    list_of_songs.append(newResults)

    prePlaylist = spotify.user_playlists(user=username)
    Playlist = prePlaylist['items'][0]['id']
    user_input = input('Enter song name: ')
spotify.user_playlist_add_tracks(user=username, playlist_id=Playlist, tracks=list_of_songs)
