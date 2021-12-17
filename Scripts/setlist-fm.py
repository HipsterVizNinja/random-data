from repertorio import Repertorio
api = Repertorio('r9Ig8-9ri47gELEXnpOjY2bPtgwGo87_3OtH')

import json
import pandas as pd
from pandas.io.json import json_normalize
import flat_table
instance = '21'

vw_setlist_1 = api.venue_setlists('3d7311b', p = instance)
# vw_setlist_2 = api.setlists(artistName='Vampire Weekend', p = 2)
# vw_setlist_3 = api.setlists(artistName='Vampire Weekend', p = 3)
# vw_setlist_4 = api.setlists(artistName='Vampire Weekend', p = 4)
# vw_setlist_5 = api.setlists(artistName='Vampire Weekend', p = 5)


vw_setlist_1_df = json_normalize(vw_setlist_1['setlist'])
# vw_setlist_2_df = json_normalize(vw_setlist_2['setlist'])
# vw_setlist_3_df = json_normalize(vw_setlist_3['setlist'])
# vw_setlist_4_df = json_normalize(vw_setlist_4['setlist'])
# vw_setlist_5_df = json_normalize(vw_setlist_5['setlist'])

vw_songs_1_df = flat_table.normalize(vw_setlist_1_df)
# vw_songs_2_df = flat_table.normalize(vw_setlist_2_df)
# vw_songs_3_df = flat_table.normalize(vw_setlist_3_df)
# vw_songs_4_df = flat_table.normalize(vw_setlist_4_df)
# vw_songs_5_df = flat_table.normalize(vw_setlist_5_df)

cbgb = pd.concat([vw_songs_1_df], axis=0)

# instance_int = instance.to_str
cbgb.to_csv('/Users/sm029588/Desktop/cbgb_tour'+instance+'.csv')
# files.download('FOTB_tour.csv')