import pandas as pd
import numpy as np
from pathlib import Path


def load_new_data(file_path: Path) -> pd.DataFrame:
    """Load and preprocess the new Billboard data extract."""
    df = pd.read_csv(
        file_path,
        usecols=['url', 'Chart Position', 'Song', 'Performer']
    )
    df = df.rename(columns={
        'Chart Position': 'chart_position',
        'Song': 'song',
        'Performer': 'performer'
    })

    # Safer song identifier
    df["song_id"] = (
        df['song'].str.strip().str.lower()
        + "|" +
        df['performer'].str.strip().str.lower()
    )

    # Extract chart_date from URL
    df['chart_date'] = pd.to_datetime(
        df['url'].str.extract(r'(\d{4}-\d{2}-\d{2})')[0]
    )
    return df.drop(columns=['url'])


def load_master(file_path: Path) -> pd.DataFrame:
    """Load the master Hot 100 dataset."""
    return pd.read_csv(
        file_path,
        usecols=['chart_position', 'song', 'performer',
                 'song_id', 'chart_date'],
        parse_dates=['chart_date']
    )


def build_full_dataset(df_new: pd.DataFrame, df_master: pd.DataFrame) -> pd.DataFrame:
    """Combine new and master data, deduplicate, and compute chart metrics."""
    df_all = pd.concat([df_new, df_master]).drop_duplicates(
        subset=['song_id', 'chart_date']
    )

    df_all.sort_values(['song_id', 'chart_date'], inplace=True)
    df_all.reset_index(drop=True, inplace=True)

    # Debut date
    df_all['chart_debut'] = df_all.groupby('song_id')['chart_date'].transform('min')

    # Time on chart (total weeks since debut, not consecutive)
    df_all['time_on_chart'] = df_all.groupby('song_id').cumcount() + 1

    # Consecutive weeks logic
    df_all['days_since_last'] = df_all.groupby('song_id')['chart_date'].diff()
    df_all['is_consecutive'] = (df_all['days_since_last'] == pd.Timedelta(days=7)).astype(int)
    df_all['reset'] = (df_all['is_consecutive'] == 0).astype(int)
    df_all['cumsum'] = df_all.groupby('song_id')['reset'].cumsum()
    df_all['consecutive_weeks'] = (
        df_all.groupby(['song_id', 'cumsum']).cumcount() + 1
    )

    # Instance counter (how many separate chart runs a song had)
    df_all['instance'] = df_all.groupby('song_id')['reset'].cumsum()

    # Previous week rank
    df_all['previous_rank'] = df_all.groupby('song_id')['chart_position'].shift(1)
    df_all['previous_week'] = df_all['previous_rank'].where(
        df_all['days_since_last'] == pd.Timedelta(days=7)
    )

    # Peak and worst positions
    df_all['peak_position'] = df_all.groupby('song_id')['chart_position'].cummin()
    df_all['worst_position'] = df_all.groupby('song_id')['chart_position'].cummax()

    # Replace 0 with NaN for consistency
    df_all['consecutive_weeks'] = df_all['consecutive_weeks'].replace(0, np.nan)
    df_all['previous_week'] = df_all['previous_week'].replace(0, np.nan)

    # Chart URL
    df_all['chart_url'] = (
        'https://www.billboard.com/charts/hot-100/' +
        df_all['chart_date'].dt.strftime('%Y-%m-%d')
    )

    return df_all


def save_dataset(df: pd.DataFrame, file_path: Path) -> None:
    """Save final dataset to CSV."""
    df.to_csv(
        file_path,
        index=False,
        columns=[
            'chart_position', 'chart_date', 'song', 'performer',
            'song_id', 'instance', 'time_on_chart', 'consecutive_weeks',
            'previous_week', 'peak_position', 'worst_position',
            'chart_debut', 'chart_url'
        ]
    )


def main(new_file: Path, master_file: Path) -> None:
    df_new = load_new_data(new_file)
    df_master = load_master(master_file)
    df_all = build_full_dataset(df_new, df_master)
    save_dataset(df_all, master_file)
    print(df_all)


if __name__ == "__main__":
    # Update these paths as needed
    data_dir = Path.home() / "Documents/GitHub/random-data/Music/hot-100"
    new_file = Path.home() / "Downloads/billboard.csv"
    master_file = data_dir / "Hot 100.csv"

    main(new_file, master_file)
