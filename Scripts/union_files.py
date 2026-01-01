import pandas as pd
import glob

# Get all CSV files matching the pattern
files = glob.glob('/Users/seanmiller/Downloads/Big Buys POS*.csv')

# Read and combine all files
dfs = []
for file in files:
    df = pd.read_csv(file, low_memory=False)
    dfs.append(df)
    print(f"Loaded {file}: {len(df)} rows")

# Combine all dataframes
combined = pd.concat(dfs, ignore_index=True)
print(f"\nTotal rows before dedup: {len(combined)}")

# Remove duplicates
# combined = combined.drop_duplicates()
# print(f"Total rows after dedup: {len(combined)}")
# print(f"Duplicates removed: {len(pd.concat(dfs, ignore_index=True)) - len(combined)}")

# Sort by date and order id
combined = combined.sort_values(['Order Number', 'Date'], ascending=[True, True])
print(f"\nSorted by date and order_id")

# Save to master file
output_file = '/Users/seanmiller/Downloads/Big Guys POS_lab.csv'
combined.to_csv(output_file, index=False)
print(f"\nMaster file saved: {output_file}")