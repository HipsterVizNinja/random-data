import csv
import json


header = []
results = []
with open('/Users/sean.miller/Downloads/extended_movies/relationships/HAS_GENRE.csv', 'r') as f:
    reader = csv.reader(f)
    for row in reader:
        if len(header) > 0:
            location = {}
            datarow = {}
            for key, value in (zip(header,row)):
                if key.startswith('location'):
                    location[key.split('/')[1]] = value
                else:
                    datarow[key] = value
            datarow['location'] = location
            results.append(datarow)
        else:
            header = row
# Sort the results list by internalid key
results = sorted(results, key=lambda x: int(x['startNodeInternalId']))

with open('/Users/sean.miller/Downloads/extended_movies/relationships/Has_genre.json', 'w') as outfile:
    for result in results:
        json.dump(result, outfile)
        outfile.write('\n')
