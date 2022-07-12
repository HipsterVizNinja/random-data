import pylast 
# You have to have your own unique two values for API_KEY and API_SECRET
# Obtain yours from https://www.last.fm/api/account/create for Last.fm
API_KEY = "KEY"  # this is a sample key
API_SECRET = "SECRET"

# In order to perform a write operation you need to authenticate yourself
username = "USER"
password_hash = pylast.md5("PASSWORD")

network = pylast.LastFMNetwork(
    api_key=API_KEY,
    api_secret=API_SECRET,
    username=username,
    password_hash=password_hash,
)
track = network.get_track("ARTIST", "SONG TITLE")
#Get the tags a a TopItem object. 
topItems = track.get_top_tags(limit=1)
for topItem in topItems:
    print (topItem.item.get_name(), topItem.weight)

