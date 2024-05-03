import pandas as pd
import numpy as np

# Set settings for dataframe
pd.set_option('display.max_rows', 1000)
pd.options.display.max_colwidth = 150
pd.set_option('display.max_columns', None)

# Let's bring it in
df = pd.read_csv('/Users/sean_miller/Downloads/billboard.csv', usecols=['url', 'Chart Position', 'Song', 'Performer'])
df = df.rename(columns={'Chart Position':'chart_position', 'Song':'song', 'Performer':'performer',})

# Create Song identifier
df["song_id"] = df['song']+df['performer']

# Extract Date from URL
df['chart_date'] = pd.to_datetime(df['url'].str.extract('(\d{4}-\d{2}-\d{2})')[0])
df = df.drop(['url'],axis= 1)

# Open an existing dataframe
df_master = pd.read_csv('/Users/sean_miller/Library/CloudStorage/OneDrive-Concord/Documents/Code/random-data/Music/hot-100/Hot 100.csv', usecols=['chart_position', 'song', 'performer', 'song_id', 'chart_date'], parse_dates=['chart_date'])

# append each file to the "master" dataframe
df_all = pd.concat([df,df_master])

# Need to test new code on a subset?
# df_all = df_all.loc[df_all['song_id'] == 'All I Want For Christmas Is YouMariah Carey']

# Good to make sure everything is sorted properly
df_all.sort_values(['song_id', 'chart_date'], ascending=[True, True], inplace=True)
df_all.reset_index(drop=True, inplace=True)

# When was the first time a song landed on the chart?
df_all['chart_debut'] = df_all.groupby('song_id')["chart_date"].transform('min')

# # How many total weeks has it been since the debut?
df_all['time_on_chart'] = df_all.groupby('song_id').cumcount() + 1

# # For each song, let's find out how many consecutive weeks it's been on the chart
df_all['days_since_last'] = df_all.groupby(['song_id'])['chart_date'].diff()
df_all.loc[df_all['days_since_last'] == '7 days', 'is_consecutive'] = 1
df_all.loc[df_all['days_since_last'] != '7 days', 'is_consecutive'] = 0
df_all.loc[df_all['is_consecutive'] == 0, 'reset'] = 1
df_all.loc[df_all['is_consecutive'] == 1, 'reset'] = 0
df_all['cumsum'] = df_all['reset'].cumsum()
df_all['consecutive_weeks'] = df_all.groupby(['song_id','cumsum'])['is_consecutive'].cumsum()

# # How many times has a song reappeared on the chart
df_all['instance'] = df_all.groupby('song_id')['reset'].cumsum()

# What was the song's previous rank
df_all['previous_rank'] = df_all.groupby(['song_id'])['chart_position'].shift(1)
df_all.loc[df_all['days_since_last'] == '7 days', 'previous_week'] = df_all['previous_rank']
df_all.loc[df_all['days_since_last'] != '7 days', 'previous_week'] = 0

# What's the highest & lowest position a song has been
df_all['peak_position'] = df_all.groupby(['song_id'])['chart_position'].cummin()
df_all['worst_position'] = df_all.groupby(['song_id'])['chart_position'].cummax()

# Null out the zeros
df_all['consecutive_weeks'] = df_all['consecutive_weeks'].replace(0, np.nan)
df_all['previous_week'] = df_all['previous_week'].replace(0, np.nan)

# Create Chart URL
chart_dt = df_all['chart_date'].dt.strftime('%Y-%m-%d')
df_all['chart_url'] = 'https://www.billboard.com/charts/hot-100/'+chart_dt

# Output
df_all.to_csv('/Users/sean_miller/Library/CloudStorage/OneDrive-Concord/Documents/Code/random-data/Music/hot-100/Hot 100.csv', index=False, columns=['chart_position', 'chart_date', 'song', 'performer', 'song_id','instance', 'time_on_chart', 'consecutive_weeks', 'previous_week', 'peak_position', 'worst_position', 'chart_debut', 'chart_url'])

print(df_all)