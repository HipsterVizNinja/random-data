# 1. Read in the main dataset

import pandas as pd

import numpy as np

main = pd.read_csv('/Users/sean.miller/Downloads/extended_movies/nodes/Tom-Hanks.csv')

# 2.  Take a unique list of the two network columns (Actor and Movie)

movies = main.title.unique()

actors = main.Name.unique()

# 3. Concatenate the two list into one array

label = np.concatenate([movies, actors])

# 4. Create the nodes dataframe from the label array

nodes = pd.DataFrame(label, columns = ['Label'])

# 5. Add the ID and Nodes unique identifier columns

nodes['ID'] = range(1, 1 + len(nodes))

nodes['Nodes'] = range(1, 1 + len(nodes))

# 6. Export the nodes dataframe as a CSV

nodes.to_csv('/Users/sean.miller/Downloads/extended_movies/nodes/Tom-Hanks-nodes.csv', index = False)
# use the map() function to add the columns with data from nodes
main['Source'] = main.title.map(nodes.set_index('Label')['Nodes'].to_dict())

main['Target'] = main.Name.map(nodes.set_index('Label')['Nodes'].to_dict())

# 1. Grab the Source and Target columns from main

edges = main[['Source', 'Target']]

# 2. Add the Type and Directed columns

edges.insert(2, 'Type', "Directed")

edges.insert(3, 'Weight', 1)

 

# 3. Export the edges dataframe as a CSV

edges.to_csv('/Users/sean.miller/Downloads/extended_movies/nodes/Tom-Hanks-edge.csv', index = False)

 

# 4. Export the main data frame as a CSV 

main.to_csv('/Users/sean.miller/Downloads/extended_movies/nodes/Tom-Hanks-main.csv', index = False)

# 1. Read in the main dataset

main = pd.read_csv('/Users/sean.miller/Downloads/extended_movies/nodes/Tom-Hanks-main.csv')

# 2. Read in the network dataset 

network = pd.read_excel('/Users/sean.miller/Downloads/extended_movies/nodes/network.xlsx')

# 3. Merge the ‘x’ and ‘y’ coordinates corresponding to the “Target” value for each main dataset combination. Save this as a new dataframe

target = main.merge(network[['x', 'y', 'value']], how='left', left_on= 'Target', right_on= 'value').drop(columns=['value'])
                    # left_on = ‘Target’, right_on = ‘value’).drop(columns = [‘value’])

# 4. Merge the ‘x’ and ‘y’ coordinates corresponding to the “Source” value for each main dataset combination. Save this as a new dataframe

source = main.merge(network[['x', 'y', 'value']], how='left', left_on='Source', right_on='value').drop(columns= ['value'])


# 5. Append the source data to target and save it as main

main = target.append(source)

# 6. Export main as a CSV

main.to_csv('/Users/sean.miller/Downloads/extended_movies/nodes/Tom-Hanks-main.csv', index = False)