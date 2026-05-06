# DCA Analyzer 🚀

A premium Python utility to analyze and optimize your Dollar Cost Averaging (DCA) strategy for US Market Indices (S&P 500, NASDAQ). Determine the mathematically optimal day of the month to invest based on 20 years of historical data.

![DCA Analysis Example](media/dca_analysis.png)

## ✨ Features

- **Optimal Day Discovery**: Analyzes every day of the month (1-31) to find the maximum ROI.
- **Hourly/Intraday Accuracy**: Support for high-fidelity price matching using various intervals (`1h`, `30m`, `15m`, etc.).
- **Market-Aware Logic**: Correctly handles US market closures (weekends/holidays) by deferring buys to the next market open.
- **Premium Visualizations**: Professional dark-themed dashboard with dynamic ROI offsets to highlight subtle performance differences.
- **Smart Caching**: Built-in SQLite layer to cache historical data, making subsequent runs near-instant.
- **Flexible Configuration**: Manage your investment amount, time horizon, and tickers via environment variables.
- **Modern Tooling**: Powered by `uv` for lightning-fast dependency management.

## 🛠️ Prerequisites

- **Python 3.12+**
- **uv**: The extremely fast Python package manager. [Install uv](https://github.com/astral-sh/uv).

## 🚀 Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/supat-roong/DCA-analyzer.git
   cd dca-analyzer
   ```

2. **Setup environment variables**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to customize your settings:
   - `YEARS`: History length.
   - `MONTHLY_INVESTMENT`: Amount to invest each month.
   - `INTERVAL`: Data granularity (`1d`, `1h`, `30m`, `15m`, `1m`).
     > **Note**: `1h` is limited to 2 years. Intervals smaller than `1h` (e.g., `30m`, `15m`) are limited to 60 days. `1m` is limited to 7 days.
   - `INDICES`: Tickers to analyze.
   - `TIMEZONE`: Your local timezone (e.g., `Asia/Bangkok`).
   - `EXECUTION_HOUR`: The hour of day to execute (0-23).

3. **Run the analysis**:
   ```bash
   uv run analyzer.py
   ```

## 📊 Project Structure

```text
.
├── analyzer.py          # Core simulation and plotting logic
├── data/               # Generated CSV reports (ignored by git)
├── db/                 # SQLite cache database (ignored by git)
├── media/              # Analysis charts and images (ignored by git)
├── .env                # Local configuration (ignored by git)
├── pyproject.toml      # Project dependencies and metadata
└── uv.lock             # Deterministic lockfile
```

## 🧠 Simulation Logic

The analyzer simulates a dynamic execution based on your `.env` configuration (`TIMEZONE` and `EXECUTION_HOUR`):

- **Post-Session Execution**: If the trigger occurs after the US market has closed (4:00 PM ET), the simulation buys at that session's **Close** price.
- **Pre-Session / Intraday Execution**: If the trigger occurs before or during a US market session, it buys at the **Open** price of that session (simulating a "buy as soon as possible" entry).
- **Market Closed**: If the trigger occurs on a weekend or holiday, the simulation waits and buys at the **Open** price of the next available US trading session.

## 📜 License

MIT
