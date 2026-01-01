import pandas as pd
from timezonefinder import TimezoneFinder

# Input and output file paths
input_path = "/Users/seanmiller/Downloads/Locations.xlsx"
output_path = "/Users/seanmiller/Downloads/Locations_with_timezone.xlsx"

# Read the Excel file
df = pd.read_excel(input_path)

# Create timezone finder instance
tf = TimezoneFinder()

# Add a new column for timezone
df["timezone"] = df.apply(lambda x: tf.timezone_at(lat=x["latitude"], lng=x["longitude"]), axis=1)

# Write updated data to a new Excel file
df.to_excel(output_path, index=False)

print(f"Timezone lookup complete. File saved to: {output_path}")