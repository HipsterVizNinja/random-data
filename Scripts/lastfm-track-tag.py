import pylast
import csv

# You have to have your own unique two values for API_KEY and API_SECRET
# Obtain yours from https://www.last.fm/api/account/create for Last.fm
API_KEY = "KEY"  # this is a sample key
API_SECRET = "SECRET"

# In order to perform a write operation you need to authenticate yourself
username = "USERNAME"
password_hash = pylast.md5("PASSWORD")

network = pylast.LastFMNetwork(
    api_key=API_KEY,
    api_secret=API_SECRET,
    username=username,
    password_hash=password_hash,
)

# Set up the output - just paste your file path in line 10. Change nothing else
with open('OUTPUT FILE', 'w', newline='') as csv_output:
    csv_writer = csv.writer(csv_output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    csv_writer.writerow(
        ["Performer", "Song", "Tag", "Weight"])

# Paste the input file path with the following columns in this order: SongID, Song, Performer
    i = 0
    with open('INPUT FILE') as csv_input:
        csv_reader = csv.DictReader(csv_input, delimiter=',')
        for song in csv_reader:
            i += 1

            artist_name = song["Performer"]
            track_name = song["Song"]

            track = network.get_track(artist_name, track_name)
            #Get the tags a a TopItem object. 
            topItems = track.get_top_tags(limit=1)
            for topItem in topItems:
                row_to_write = (artist_name,track_name,topItem.item.get_name(), topItem.weight)
            print(row_to_write)
            csv_writer.writerow(row_to_write)