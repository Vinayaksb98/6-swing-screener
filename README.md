# NSE Momentum Screener — Streamlit deployment package

## Repository root must contain
- `app.py`
- `requirements.txt`
- `README.md` (optional for deployment)

Do not upload the ZIP itself into GitHub and expect Streamlit to run it. Extract the ZIP first, then upload the files directly to the repository root.

## Dependencies
`requirements.txt` intentionally uses unpinned package names so pip can choose builds compatible with the Python runtime selected by Streamlit Community Cloud. This avoids an older NumPy pin failing on newer Python runtimes.

## Deploy
1. Create a clean GitHub repository.
2. Extract this ZIP and upload `app.py` and `requirements.txt` directly to the repository root (not inside a nested folder).
3. In Streamlit Community Cloud, create an app from that repository, choose the correct branch, and set the main file path to `app.py`.
4. If asked to choose Python, choose Python 3.12 for broad dependency compatibility.
5. If deployment still fails, open **Manage app → Logs** and copy the first red error / `ModuleNotFoundError` line.

## App notes
The app scans daily Yahoo Finance data, applies the EMA/RSI/volume filters, and can send Telegram alerts when requested. Yahoo Finance and the Nifty Indices constituent source can occasionally be unavailable or rate-limited.
