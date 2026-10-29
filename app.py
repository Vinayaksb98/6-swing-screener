import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import datetime

st.set_page_config(page_title="NSE Momentum Screener", page_icon="📊", layout="wide")
st.title("📊 NSE Midcap & Momentum Screener")
st.markdown(
    "Scans for **Price > 20 EMA, 10 EMA > 20 EMA, RSI 55–68, and Volume ≥ 1.5× "
    "the 10-day average**, with indicative trigger, stop-loss, and targets."
)

NIFTY500_CSV_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
FALLBACK_STOCKS = [
    "HAL.NS", "BEL.NS", "BDL.NS", "COCHINSHIP.NS", "MAZDOCK.NS",
    "POLYCAB.NS", "KEI.NS", "DIXON.NS", "SUPRAJIT.NS", "CAMS.NS",
    "PERSISTENT.NS", "LTTS.NS", "KPITTECH.NS", "COFORGE.NS", "TATAELXSI.NS",
    "APLAPOLLO.NS", "ASTRAL.NS", "SUPREMEIND.NS", "PIDILITEIND.NS", "SRF.NS"
]

@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def get_nifty500_stocks():
    """Fetch the current Nifty 500 constituents; fall back to a small sample if unavailable."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,*/*",
        "Referer": "https://www.niftyindices.com/"
    }
    try:
        response = requests.get(NIFTY500_CSV_URL, headers=headers, timeout=15)
        response.raise_for_status()
        from io import StringIO
        constituents = pd.read_csv(StringIO(response.text))
        symbol_col = next(
            (c for c in constituents.columns if str(c).strip().lower() in ("symbol", "ticker")),
            None
        )
        if symbol_col is None:
            raise ValueError("Symbol column was not found in the Nifty 500 CSV.")
        symbols = (
            constituents[symbol_col].dropna().astype(str).str.strip().str.upper()
            .loc[lambda s: s.ne("")]
            .drop_duplicates().tolist()
        )
        if not symbols:
            raise ValueError("Nifty 500 CSV returned no symbols.")
        return [s if s.endswith(".NS") else f"{s}.NS" for s in symbols], "Nifty 500 constituents"
    except Exception:
        return FALLBACK_STOCKS.copy(), "Fallback sample (Nifty 500 list could not be fetched)"

def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # A consistently rising series has RSI 100; avoid treating it as missing.
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0)
    return rsi

def send_telegram_message(token, chat_id, message):
    if not token or not chat_id:
        return False, "Enter both the Telegram Bot Token and Chat ID."
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        if response.ok:
            return True, "Telegram alert sent successfully."
        return False, f"Telegram returned HTTP {response.status_code}: {response.text[:250]}"
    except requests.RequestException as exc:
        return False, f"Telegram request failed: {exc}"

nifty500_stocks, universe_label = get_nifty500_stocks()

st.sidebar.header("⚙️ Screener Settings")
universe_choice = st.sidebar.radio("Stock universe", ["Nifty 500", "Custom list"])
if universe_choice == "Nifty 500":
    stock_list = nifty500_stocks
    st.sidebar.caption(f"Universe: {universe_label} · {len(stock_list)} symbols")
else:
    default_text = ", ".join(FALLBACK_STOCKS)
    selected_stocks = st.sidebar.text_area(
        "Stock symbols (comma-separated; .NS optional)", value=default_text, height=150
    )
    stock_list = []
    for symbol in selected_stocks.split(","):
        symbol = symbol.strip().upper()
        if symbol:
            stock_list.append(symbol if symbol.endswith(".NS") else f"{symbol}.NS")
    stock_list = list(dict.fromkeys(stock_list))
    st.sidebar.caption(f"Custom symbols: {len(stock_list)}")

st.sidebar.header("🤖 Telegram Alerts")
telegram_token = st.sidebar.text_input("Bot Token", type="password")
chat_id = st.sidebar.text_input("Chat ID")

st.caption(
    "Data source: Yahoo Finance daily candles. Data may be delayed, incomplete, or unavailable "
    "for some symbols. This tool is for screening, not an order-execution system."
)

def scan_stocks(symbols):
    results, errors = [], []
    progress = st.progress(0, text="Starting scan…")
    total = len(symbols)
    if total == 0:
        progress.empty()
        return results, errors

    for i, ticker in enumerate(symbols):
        try:
            df = yf.download(
                ticker, period="3mo", interval="1d", auto_adjust=False,
                progress=False, threads=False, timeout=15
            )
            if df is None or df.empty:
                errors.append((ticker, "No daily data returned"))
                continue

            if isinstance(df.columns, pd.MultiIndex):
                # yfinance may return (Price, Ticker) or (Ticker, Price).
                if "Close" in df.columns.get_level_values(0):
                    df.columns = df.columns.get_level_values(0)
                elif "Close" in df.columns.get_level_values(-1):
                    df.columns = df.columns.get_level_values(-1)
            if not {"Close", "Volume"}.issubset(df.columns):
                errors.append((ticker, "Close/Volume columns missing"))
                continue

            close = pd.to_numeric(df["Close"], errors="coerce").dropna()
            volume = pd.to_numeric(df["Volume"], errors="coerce").reindex(close.index)
            data = pd.DataFrame({"Close": close, "Volume": volume}).dropna()
            if len(data) < 30:
                errors.append((ticker, "Insufficient history"))
                continue

            close = data["Close"]
            volume = data["Volume"]
            ema10 = close.ewm(span=10, adjust=False).mean()
            ema20 = close.ewm(span=20, adjust=False).mean()
            rsi = calculate_rsi(close, 14)
            avg_volume10 = volume.rolling(10, min_periods=10).mean()

            curr_price = float(close.iloc[-1])
            curr_ema10 = float(ema10.iloc[-1])
            curr_ema20 = float(ema20.iloc[-1])
            curr_rsi = float(rsi.iloc[-1])
            curr_volume = float(volume.iloc[-1])
            avg_vol = float(avg_volume10.iloc[-1])

            if not np.isfinite([curr_price, curr_ema10, curr_ema20, curr_rsi, curr_volume, avg_vol]).all():
                errors.append((ticker, "Indicator values unavailable"))
                continue
            if avg_vol <= 0:
                errors.append((ticker, "Average volume is zero"))
                continue

            if curr_price > curr_ema20 and curr_ema10 > curr_ema20 and 55 <= curr_rsi <= 68 and curr_volume >= 1.5 * avg_vol:
                results.append({
                    "Stock": ticker.removesuffix(".NS"),
                    "Price (₹)": round(curr_price, 2),
                    "RSI": round(curr_rsi, 1),
                    "Volume / 10D Avg": round(curr_volume / avg_vol, 2),
                    "Trigger (₹)": round(curr_price * 1.002, 2),
                    "Stop Loss (₹)": round(curr_price * 0.96, 2),
                    "Target 1 (+8%) (₹)": round(curr_price * 1.08, 2),
                    "Target 2 (+12%) (₹)": round(curr_price * 1.12, 2),
                })
        except Exception as exc:
            errors.append((ticker, str(exc)[:120]))
        progress.progress((i + 1) / total, text=f"Scanned {i + 1} of {total}: {ticker}")

    progress.empty()
    return results, errors

if st.button("🚀 Run Momentum Scan", type="primary", use_container_width=True):
    if not stock_list:
        st.warning("Please provide at least one stock symbol.")
    else:
        with st.spinner(f"Scanning {len(stock_list)} stocks. This may take several minutes…"):
            found, failed = scan_stocks(stock_list)
        st.session_state["momentum_results"] = found
        st.session_state["momentum_errors"] = failed
        st.session_state["momentum_scanned"] = len(stock_list)
        st.session_state["momentum_scan_time"] = datetime.now().strftime("%d %b %Y, %I:%M %p")

if "momentum_results" in st.session_state:
    results = st.session_state["momentum_results"]
    errors = st.session_state.get("momentum_errors", [])
    scanned = st.session_state.get("momentum_scanned", 0)
    scan_time = st.session_state.get("momentum_scan_time", "")
    st.caption(f"Last scan: {scan_time} · Symbols attempted: {scanned} · Data/errors: {len(errors)}")
    if results:
        res_df = pd.DataFrame(results)
        st.success(f"Found {len(res_df)} matching setup(s).")
        st.dataframe(res_df, use_container_width=True, hide_index=True)
        csv_data = res_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download results CSV", csv_data, "nse_momentum_results.csv", "text/csv")
        if st.button("📤 Send Alerts to Telegram", use_container_width=True):
            lines = ["🚨 <b>New NSE Momentum Setups</b>", f"Scan: {scan_time}", ""]
            for row in results:
                lines.append(
                    f"<b>{row['Stock']}</b> | Price ₹{row['Price (₹)']:.2f} | RSI {row['RSI']:.1f} | "
                    f"Vol {row['Volume / 10D Avg']:.2f}x"
                )
                lines.append(
                    f"Trigger ₹{row['Trigger (₹)']:.2f} | SL ₹{row['Stop Loss (₹)']:.2f} | "
                    f"T1 ₹{row['Target 1 (+8%) (₹)']:.2f} | T2 ₹{row['Target 2 (+12%) (₹)']:.2f}"
                )
                lines.append("")
            # Telegram messages are limited; split into safe-sized chunks.
            message_chunks, current = [], ""
            for line in lines:
                candidate = current + line + "\n"
                if len(candidate) > 3500 and current:
                    message_chunks.append(current)
                    current = line + "\n"
                else:
                    current = candidate
            if current:
                message_chunks.append(current)
            all_ok = True
            for chunk in message_chunks:
                ok, detail = send_telegram_message(telegram_token, chat_id, chunk)
                if not ok:
                    all_ok = False
                    st.error(detail)
                    break
            if all_ok:
                st.success("Telegram alert(s) sent.")
    else:
        st.warning("No stocks matched all filter conditions in the last scan.")
    if errors:
        with st.expander(f"View {len(errors)} skipped/failed symbol(s)"):
            st.dataframe(pd.DataFrame(errors, columns=["Stock", "Reason"]), use_container_width=True, hide_index=True)
