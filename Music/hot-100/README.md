# Billboard-Hot-100
This repo will contain the complete historical dataset of every Billboard Hot 100 chart since 1958. Below is the data
dictionary for this dataset

## Data Dictionary
- #### chart_position
  - The position of the song for the given chart date
- #### chart_date
  - This is the date that the chart was released
- #### song
  - The name of the song
- #### performer
  - the performer of the song
- #### song_id
  - A concatenation of song and performer to create a unique identifier
- #### instance
  - This indicates how many times a song_id as returned to the chart after more than 1 week off the chart (See Mariah Carey - All I Want for Christmas is You for an example)
- #### time_on_chart
  - This is the running count of weeks (all-time) a song_id has been on the chart
- #### consecutive_weeks
  - For the given instance, how many weeks has the song_id been on the chart consecutively. A null value indicates the start of a new instance
- #### previous_week
  - For the given instance, what was the chart_position for the previous week
- #### peak_position
  - Indicates the all-time best/peak position for a song_id
- #### worst_position
  - Indicates the all-time worst/lowest position for a song_id
- #### chart_debut
  - The date of the first initial instance for a song_id
- #### chart_url
  - This URL will take you to the chart on [Billboard.com](https://www.billboard.com)

