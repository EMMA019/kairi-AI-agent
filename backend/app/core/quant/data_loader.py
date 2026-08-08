import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

US_SECTORS = {
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLK": "Technology",
    "XLU": "Utilities"
}

JP_SECTORS = {
    "1617.T": "Foods",
    "1618.T": "Energy Resources",
    "1619.T": "Construction & Materials",
    "1620.T": "Materials & Chemicals",
    "1621.T": "Pharmaceuticals",
    "1622.T": "Automobiles & Transportation",
    "1623.T": "Steel & Nonferrous Metals",
    "1624.T": "Machinery",
    "1625.T": "Electric & Precision",
    "1626.T": "IT & Services",
    "1627.T": "Electric Power & Gas",
    "1628.T": "Transportation & Logistics",
    "1629.T": "Commercial & Wholesale Trade",
    "1630.T": "Retail Trade",
    "1631.T": "Banks",
    "1632.T": "Financials (ex Banks)",
    "1633.T": "Real Estate"
}

FX_TICKER = "USDJPY=X"

def fetch_returns(tickers: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch daily returns for a list of tickers."""
    # yfinance download with progress=False
    df = yf.download(tickers, start=start_date, end=end_date, progress=False, group_by="column")
    
    # Handle single ticker case vs multiple tickers
    if isinstance(df.columns, pd.MultiIndex):
        closes = df['Close']
    else:
        closes = df[['Close']] if 'Close' in df else pd.DataFrame(df)
        closes.columns = tickers

    closes = closes.ffill() # forward fill missing data
    returns = closes.pct_change().dropna(how='all')
    returns.index = pd.to_datetime(returns.index).tz_localize(None).normalize()
    return returns

def get_aligned_lead_lag_returns(lookback_days: int = 252) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch and align US(t-1) and JP(t) daily returns.
    Returns:
        X_us: DataFrame of US returns for the prior trading day.
        Y_jp: DataFrame of JP returns for the current trading day.
    """
    end_date = datetime.now()
    # Fetch extra days to account for weekends and holidays
    start_date = end_date - timedelta(days=int(lookback_days * 1.5) + 20)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    logger.info(f"Fetching US sectors from {start_str} to {end_str}")
    us_returns = fetch_returns(list(US_SECTORS.keys()), start_str, end_str)
    
    logger.info(f"Fetching JP sectors from {start_str} to {end_str}")
    jp_returns = fetch_returns(list(JP_SECTORS.keys()), start_str, end_str)
    
    logger.info(f"Fetching FX from {start_str} to {end_str}")
    fx_returns = fetch_returns([FX_TICKER], start_str, end_str)
    
    # Alignment logic: US(t) predicts JP(t+1)
    # We want to match each JP date with the most recent US date strictly before it.
    us_dates = us_returns.index.sort_values()
    
    aligned_us_records = []
    aligned_jp_records = []
    aligned_dates = []
    
    for jp_date in jp_returns.index:
        # Find the max US date that is strictly less than JP date
        # (Since JP market opens roughly 13 hours after US market closes for the same calendar date, 
        # wait, US calendar date T closes at 4 PM EST (T). JP opens at 9 AM JST (T+1).
        # So we want US date < JP date.)
        valid_us_dates = us_dates[us_dates < jp_date]
        if len(valid_us_dates) > 0:
            us_date = valid_us_dates[-1]
            
            # Combine US sector returns with FX return for the US date
            us_rec = us_returns.loc[us_date].copy()
            # If FX is missing for that day, use 0 or previous
            us_rec['FX'] = fx_returns.loc[us_date].iloc[0] if us_date in fx_returns.index else 0.0
            
            aligned_us_records.append(us_rec)
            aligned_jp_records.append(jp_returns.loc[jp_date])
            aligned_dates.append(jp_date)
            
    X_us = pd.DataFrame(aligned_us_records, index=aligned_dates)
    Y_jp = pd.DataFrame(aligned_jp_records, index=aligned_dates)
    
    # Drop rows with NaN that might have occurred if some ETF started later
    valid_idx = X_us.dropna().index.intersection(Y_jp.dropna().index)
    X_us = X_us.loc[valid_idx].tail(lookback_days)
    Y_jp = Y_jp.loc[valid_idx].tail(lookback_days)
    
    # Reorder columns explicitly to maintain consistent order
    us_cols = [t for t in US_SECTORS.keys() if t in X_us.columns]
    if 'FX' in X_us.columns:
        us_cols.append('FX')
    X_us = X_us[us_cols]
    Y_jp = Y_jp[[t for t in JP_SECTORS.keys() if t in Y_jp.columns]]
    
    return X_us, Y_jp

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    x, y = get_aligned_lead_lag_returns(lookback_days=10)
    print("X_us shape:", x.shape)
    print("Y_jp shape:", y.shape)
    print("US Example:\n", x.tail(2))
    print("JP Example:\n", y.tail(2))
