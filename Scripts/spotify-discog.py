
import requests
CLIENT_ID = 'PASTE CLIENT ID'
CLIENT_SECRET = 'PAST CLIENT SECTRET'
AUTH_URL = 'https://accounts.spotify.com/api/token'

# POST
auth_response = requests.post(AUTH_URL, {
    'grant_type': 'client_credentials',
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET,
})

# convert the response to JSON
auth_response_data = auth_response.json()

# save the access token
access_token = auth_response_data['access_token']

headers = {
    'Authorization': 'Bearer {token}'.format(token=access_token)
}

# base URL of all Spotify API endpoints
BASE_URL = 'https://api.spotify.com/v1/'

# Track ID from the URI
track_id = 'PASTE TRACK ID' #We just need 1 song and it doesn't matter what song - you can get the id by right-clicking on a song, 
                            #selecting share and copy song link. 
                            #paste it here -> https://open.spotify.com/track/4f3NHOxgC8Bg21IJBg4cZ3?si=7c7fbb58e88541d5
                            #the id is the alpha-numeric string between the last / and the first ?
                            #grab that id string and paste in line 28

# actual GET request with proper header
r = requests.get(BASE_URL + 'audio-features/' + track_id, headers=headers)

artist_id = 'PASTE ARTIST ID' #We just need 1 song and it doesn't matter what song - you can get the id by right-clicking on a song, 
                              #selecting share and copy song link. 
                              #paste it here -> https://open.spotify.com/artist/0CbeG1224FS58EUx4tPevZ?si=i5GB50BfQm2D1VEB-M7uuA
                              #the id is the alpha-numeric string between the last / and the first ?
                              #grab that id string and paste in line 37

# pull all artists albums
r = requests.get(BASE_URL + 'artists/' + artist_id + '/albums', 
                 headers=headers, 
                 params={'include_groups': 'album', 'limit': 50}) # <- can be 'album', 'single', 'compilation', 'appears_on'
d = r.json()

for album in d['items']:
    print(album['name'], ' --- ', album['release_date'])

data = []   # will hold all track info
albums = [] # to keep track of duplicates

# loop over albums and get all tracks
for album in d['items']:
    album_name = album['name']

    # here's a hacky way to skip over albums we've already grabbed
    trim_name = album_name.split('(')[0].strip()
    #if trim_name.upper() in albums or int(album['release_date'][:4]) > 1983:
        #continue
    albums.append(trim_name.upper()) # use upper() to standardize
    
    # this takes a few seconds so let's keep track of progress    
    print(album_name)
    
    # pull all tracks from this album
    r = requests.get(BASE_URL + 'albums/' + album['id'] + '/tracks', 
        headers=headers)
    tracks = r.json()['items']
    
    for track in tracks:
        # get audio analysis 
        f = requests.get(BASE_URL + 'audio-features/' + track['id'], 
            headers=headers)
        f = f.json()
        
        # combine with album info
        f.update({
            'track_name': track['name'],
            'track_number': track['track_number'],
            'album_name': album_name,
            'short_album_name': trim_name,
            'release_date': album['release_date'],
            'album_id': album['id']
        })
        
        data.append(f)



import pandas as pd

df2 = pd.DataFrame(data)

print(df2.head)


df2.to_csv(r'PASTE FILE PATH AS .CSV')  #This needs to be the full C:\\ path to a file, the file does NOT need to exist. 
                                        #for example, if you want to save this file to your desktop, got to "home' in windows explorer
                                        #hold SHIFT and right click on the desktop folder and select "Copy as Path"
                                        #paste that path here then add a \ and name your file **DO NOT USE SPACES, USE - or _ in place of spaces**
                                        #and be sure to add .csv to the end
                                        #remember in line 46, you can specifiy what release type you will get. I like to add that to my file names
                                        #\file-name-album or \file-name-single etc
                                        #if you change line 46 and forget to change your filename, it will overwrite your file WITHOUT WARNING

df2.shape

my_list = list(df2)

print (my_list)
