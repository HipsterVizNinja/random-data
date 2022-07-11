import requests
CLIENT_ID = 'PASTE YOUR ID'
CLIENT_SECRET = 'PASTE YOUR SECRET'
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

artist_id = '1DFr97A9HnbV3SKTJFu62M'

track_id = '5R6OAv09z0kAV7Ll8olOH4'

f = requests.get(BASE_URL + 'audio-analysis/' + track_id,
                 headers=headers)
f = f.json()

import json
import pandas as pd
from pandas.io.json import json_normalize
data = f
#print(data['beats']) # example

df2 = pd.DataFrame(data['beats'])
print(df2)
df2.to_csv(r'PASTE YOUR BEATS OUTPUT FILEPATH')

df3 = pd.DataFrame(data['segments'])
print(df3)
df4 = pd.DataFrame(df3['pitches'].values.tolist())
print(df4)
df5 = pd.concat([pd.DataFrame(df3['pitches'].values.tolist()), df3], axis=1)
print(df5)
df5.to_csv(r'PASTE YOUR SEGMENTS OUTPUT FILEPATH')
df6 = pd.DataFrame(data['sections'])
print(df6)
df6.to_csv(r'PASTE YOUR SECTIONS OUTPUT FILEPATH')