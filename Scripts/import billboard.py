import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta

# Function to generate weekly chart dates
def get_weekly_dates(start_date, end_date):
    dates = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(weeks=1)  # Move to next Saturday
    return dates

# Define date range (Saturdays)
start_date = datetime(2025, 7, 26)
end_date = datetime(2025, 8, 30)
chart_dates = get_weekly_dates(start_date, end_date)

# Initialize DataFrame storage
all_data = []

# Iterate through weekly chart dates
for chart_date in chart_dates:
    url = f'https://www.billboard.com/charts/hot-100/{chart_date}'
    print(f"Scraping Billboard Hot 100 for {chart_date}...")  # Status update

    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"Failed to retrieve data for {chart_date}")
        continue

    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract song data
    for position, entry in enumerate(soup.find_all('div', class_='o-chart-results-list-row-container'), start=1):
        song = entry.h3.get_text(strip=True)
        performer = entry.h3.find_next('span').get_text(strip=True)
        all_data.append([url, position, song, performer])

# Create DataFrame with reordered columns
df = pd.DataFrame(all_data, columns=['url', 'Chart Position', 'Song', 'Performer'])

# Display first few rows
print(df.head())

# Save to CSV
df.to_csv('/Users/seanmiller/Downloads/billboard.csv', index=False)
print("Data saved to billboard.csv")