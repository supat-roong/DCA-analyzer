import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import pytz
import matplotlib.pyplot as plt
import seaborn as sns
import sqlite3
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration with defaults
YEARS = int(os.getenv("YEARS", 2))
MONTHLY_INVESTMENT = float(os.getenv("MONTHLY_INVESTMENT", 1000))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Bangkok")
EXECUTION_HOUR = int(os.getenv("EXECUTION_HOUR", 6))
INTERVAL = os.getenv("INTERVAL", "1d")

# Parse INDICES from .env (format: "Name1:Ticker1,Name2:Ticker2")
indices_raw = os.getenv("INDICES", "S&P 500:^GSPC,NASDAQ:^IXIC")
INDICES = {}
for pair in indices_raw.split(","):
    if ":" in pair:
        name, ticker = pair.split(":")
        INDICES[name.strip()] = ticker.strip()

# File Paths
DB_DIR = "db"
DATA_DIR = "data"
MEDIA_DIR = "media"
DB_PATH = f"{DB_DIR}/dca_cache.db"

# yfinance interval limits (approximate days)
INTERVAL_LIMITS = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "1h": 730,
    "90m": 60,
}

# Create directories if they don't exist
for d in [DB_DIR, DATA_DIR, MEDIA_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

def save_to_db(df, ticker, conn):
    if df.empty:
        return
    df_save = df.copy()
    df_save.index.name = 'Timestamp'
    if isinstance(df_save.columns, pd.MultiIndex):
        df_save.columns = [f"{col[0]}" for col in df_save.columns]
    
    df_save['ticker'] = ticker
    df_save['interval'] = INTERVAL
    df_save.to_sql('prices', conn, if_exists='append', index=True)
    
    # Deduplicate
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM prices 
        WHERE rowid NOT IN (
            SELECT min(rowid) 
            FROM prices 
            GROUP BY ticker, Timestamp, interval
        )
    """)
    conn.commit()

def sync_data(tickers, years):
    now = datetime.now()
    # Start from New Year of (current_year - years)
    start_year = now.year - years
    start_date = datetime(start_year, 1, 1)
    end_date = now
    
    # Apply yfinance limits
    limit_days = INTERVAL_LIMITS.get(INTERVAL)
    if limit_days:
        max_start = end_date - timedelta(days=limit_days - 1)
        if start_date < max_start:
            start_date = max_start

    conn = sqlite3.connect(DB_PATH)
    
    for ticker in tickers:
        # Check existing range
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT MIN(Timestamp), MAX(Timestamp) FROM prices WHERE ticker='{ticker}' AND interval='{INTERVAL}'")
            res = cursor.fetchone()
            db_min = pd.to_datetime(res[0]).replace(tzinfo=None) if res[0] else None
            db_max = pd.to_datetime(res[1]).replace(tzinfo=None) if res[1] else None
        except Exception:
            db_min, db_max = None, None

        # 1. Forward Sync
        buffer = timedelta(days=1) if INTERVAL == "1d" else timedelta(hours=1)
        forward_start = db_max if db_max else start_date
        if forward_start < (end_date - buffer).replace(tzinfo=None):
            print(f"Syncing {ticker} ({INTERVAL}) forward from {forward_start.date()}...")
            df_new = yf.download(ticker, start=forward_start, end=end_date, interval=INTERVAL, progress=False)
            save_to_db(df_new, ticker, conn)

        # 2. Backward Sync
        if db_min and db_min > (start_date + timedelta(days=2)).replace(tzinfo=None):
            print(f"Syncing {ticker} ({INTERVAL}) backward to {start_date.date()}...")
            df_old = yf.download(ticker, start=start_date, end=db_min, interval=INTERVAL, progress=False)
            save_to_db(df_old, ticker, conn)

    conn.close()

def get_data_from_cache(ticker, years):
    now = datetime.now()
    start_year = now.year - years
    start_date = datetime(start_year, 1, 1)
    
    # Exclude current month for fair comparison
    # End date is the last day of the previous month
    last_month_end = now.replace(day=1) - timedelta(seconds=1)
    
    # Apply limits for the query
    limit_days = INTERVAL_LIMITS.get(INTERVAL)
    if limit_days:
        max_start = now - timedelta(days=limit_days - 1)
        if start_date < max_start:
            start_date = max_start

    conn = sqlite3.connect(DB_PATH)
    query = f"""
        SELECT * FROM prices 
        WHERE ticker='{ticker}' 
        AND interval='{INTERVAL}' 
        AND Timestamp >= '{start_date.strftime('%Y-%m-%d %H:%M:%S')}'
        AND Timestamp <= '{last_month_end.strftime('%Y-%m-%d %H:%M:%S')}'
    """
    df = pd.read_sql(query, conn, index_col='Timestamp', parse_dates=['Timestamp'])
    conn.close()
    return df

def simulate_dca(df, day_of_month):
    """
    Simulate DCA on a specific day of the month.
    Logic: Trigger at EXECUTION_HOUR in TIMEZONE on 'day_of_month'.
    """
    total_shares = 0
    total_invested = 0
    
    # Prepare date/time info
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    
    # Filter unique months from the index (stripping TZ to avoid warning)
    unique_months = pd.Series(df.index).dt.tz_localize(None).dt.to_period('M').unique()
    
    local_tz = pytz.timezone(TIMEZONE)
    us_tz = pytz.timezone("America/New_York")
    
    from datetime import time
    market_open = time(9, 30)
    market_close = time(16, 0)
    
    for month_period in unique_months:
        yr, mn = month_period.year, month_period.month
        
        # Target execution time in local timezone
        target_day = int(min(day_of_month, pd.Timestamp(yr, mn, 1).days_in_month))
        try:
            trigger_time = local_tz.localize(datetime(yr, mn, target_day, EXECUTION_HOUR, 0))
        except (ValueError, pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
            trigger_time = local_tz.localize(datetime(yr, mn, target_day, EXECUTION_HOUR, 0), is_dst=None)
            
        # Convert trigger time to US time (with TZ awareness)
        us_time = trigger_time.astimezone(us_tz)
        us_time_only = us_time.time()
        us_date = us_time.date()
        
        # Data filtering based on timestamps
        if us_time_only >= market_close:
            # Market closed for the day. Use today's last available price.
            today_data = df[df.index.date == us_date]
            if not today_data.empty:
                buy_date = today_data.index[-1]
                price_data = today_data.loc[buy_date, 'Close']
                price = float(price_data.iloc[0]) if isinstance(price_data, pd.Series) else float(price_data)
            else:
                # Holiday/Weekend, wait for next Open
                next_data = df[df.index > us_time]
                if not next_data.empty:
                    buy_date = next_data.index[0]
                    price_data = df.loc[buy_date, 'Open']
                    price = float(price_data.iloc[0]) if isinstance(price_data, pd.Series) else float(price_data)
                else: continue

        elif us_time_only < market_open:
            # Market hasn't opened today. Wait for today's Open (or next trading day).
            next_data = df[df.index >= us_time]
            if not next_data.empty:
                buy_date = next_data.index[0]
                price_data = df.loc[buy_date, 'Open']
                price = float(price_data.iloc[0]) if isinstance(price_data, pd.Series) else float(price_data)
            else: continue
            
        else:
            # Market is currently OPEN
            if INTERVAL == '1d':
                # Daily data: Use today's Open
                today_data = df[df.index.date == us_date]
                if not today_data.empty:
                    buy_date = today_data.index[0]
                    price_data = today_data.loc[buy_date, 'Open']
                    price = float(price_data.iloc[0]) if isinstance(price_data, pd.Series) else float(price_data)
                else:
                    next_data = df[df.index > us_time]
                    if not next_data.empty:
                        buy_date = next_data.index[0]
                        price_data = df.loc[buy_date, 'Open']
                        price = float(price_data.iloc[0]) if isinstance(price_data, pd.Series) else float(price_data)
                    else: continue
            else:
                # Hourly data: Use the price of the current hour
                available = df[df.index <= us_time]
                if not available.empty and available.index[-1].date() == us_date:
                    buy_date = available.index[-1]
                    price_data = available.loc[buy_date, 'Close']
                    price = float(price_data.iloc[0]) if isinstance(price_data, pd.Series) else float(price_data)
                else:
                    # No data yet today (gap?), wait for next available
                    next_data = df[df.index > us_time]
                    if not next_data.empty:
                        buy_date = next_data.index[0]
                        price_data = df.loc[buy_date, 'Open']
                        price = float(price_data.iloc[0]) if isinstance(price_data, pd.Series) else float(price_data)
                    else: continue
                
        if price > 0:
            shares = MONTHLY_INVESTMENT / price
            total_shares += shares
            total_invested += MONTHLY_INVESTMENT
            
    final_price_data = df['Close'].iloc[-1]
    if isinstance(final_price_data, (pd.Series, pd.DataFrame)):
        final_price = float(final_price_data.iloc[0])
    else:
        final_price = float(final_price_data)
        
    final_value = total_shares * final_price
    profit = final_value - total_invested
    roi = (profit / total_invested) * 100 if total_invested > 0 else 0
    
    return {
        'day': day_of_month,
        'invested': total_invested,
        'final_value': final_value,
        'roi': roi,
        'shares': total_shares
    }

def main():
    # Use a premium dark theme
    plt.style.use('dark_background')
    plt.rcParams['font.family'] = 'sans-serif'
    
    # Batch sync all tickers first
    tickers = list(INDICES.values())
    sync_data(tickers, YEARS)
    
    results = {}
    
    for name, ticker in INDICES.items():
        df = get_data_from_cache(ticker, YEARS)
        if df.empty:
            print(f"Error: No data found for {ticker}")
            continue
            
        index_results = []
        for day in range(1, 32):
            res = simulate_dca(df, day)
            index_results.append(res)
            
        results[name] = pd.DataFrame(index_results)
        
        # Best day info
        best_day = results[name].loc[results[name]['final_value'].idxmax()]
        print(f"\n--- {name} Results ---")
        print(f"Best day: {int(best_day['day'])} | ROI: {best_day['roi']:.2f}% | Final: ${best_day['final_value']:,.2f}")
        
    # Plotting
    fig, axes = plt.subplots(2, 1, figsize=(16, 12), facecolor='#121212')
    fig.suptitle(f"DCA Performance Analysis (Past {YEARS} Years)", fontsize=24, color='white', fontweight='bold', y=0.98)
    
    colors = ['#7b2cbf', '#3a86ff'] # Deep Purple and Vivid Blue
    accent_color = '#ffd700' # Gold
    
    for i, (name, df_res) in enumerate(results.items()):
        ax = axes[i]
        ax.set_facecolor('#1e1e1e')
        
        # Calculate ROI offset to see differences better
        roi_min = df_res['roi'].min()
        roi_max = df_res['roi'].max()
        roi_range = roi_max - roi_min
        ax.set_ylim(roi_min - (roi_range * 0.1), roi_max + (roi_range * 0.2))
        
        # Bar chart with gradient-like coloring
        sns.barplot(x='day', y='roi', data=df_res, ax=ax, palette='magma', alpha=0.8, hue='day', legend=False)
        
        # Highlight best day
        best_idx = df_res['roi'].idxmax()
        best_day_num = int(df_res.iloc[best_idx]['day'])
        best_roi = df_res.iloc[best_idx]['roi']
        
        ax.patches[best_idx].set_facecolor(accent_color)
        ax.patches[best_idx].set_alpha(1.0)
        ax.patches[best_idx].set_edgecolor('white')
        ax.patches[best_idx].set_linewidth(2)
        
        # Annotation for best day
        ax.annotate(f"Best: Day {best_day_num}\n{best_roi:.1f}%", 
                    xy=(best_idx, best_roi), 
                    xytext=(0, 20), textcoords='offset points',
                    ha='center', va='bottom', color=accent_color,
                    fontweight='bold', fontsize=12,
                    bbox=dict(boxstyle='round,pad=0.5', fc='#2d2d2d', alpha=0.9, ec=accent_color))
        
        ax.set_title(f"{name} Index - ROI % by DCA Day", fontsize=18, pad=20, color='white')
        ax.set_ylabel("ROI (%)", fontsize=14)
        ax.set_xlabel("Day of Month", fontsize=14)
        ax.grid(axis='y', linestyle='--', alpha=0.3)
        
        # Summary Box
        summary_text = (
            f"Total Invested: ${df_res.iloc[best_idx]['invested']:,.0f}\n"
            f"Best Portfolio: ${df_res.iloc[best_idx]['final_value']:,.0f}\n"
            f"Max ROI: {best_roi:.2f}%"
        )
        ax.text(0.98, 0.95, summary_text, transform=ax.transAxes, 
                verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round,pad=0.8', fc='#2d2d2d', alpha=0.8, ec='gray'),
                color='white', fontsize=11, family='monospace')

    plt.tight_layout(rect=(0, 0.03, 1, 0.95))
    output_path = os.path.join(MEDIA_DIR, 'dca_analysis.png')
    plt.savefig(output_path, dpi=120)
    print(f"\nAnalysis complete. Premium chart saved as '{output_path}'.")
    
    # Save CSVs
    for name, df_res in results.items():
        filename = f"dca_{name.lower().replace(' ', '_')}.csv"
        filepath = os.path.join(DATA_DIR, filename)
        df_res.to_csv(filepath, index=False)
        print(f"Data saved to {filepath}")

if __name__ == "__main__":
    main()
