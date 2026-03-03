# Kite App Main

A Flask-based trading dashboard for monitoring option strategy data (iron condor metrics), live P&L, and manual position exits using Kite Connect.

## Features

- Live option data endpoint (`/option_data`)
- Live P&L endpoint (`/pnl`)
- Manual exit trigger endpoint (`/manual_exit`)
- Background threads for:
  - option-chain and strategy metric refresh
  - spread monitoring and risk-based exits
- Session verification with automatic token refresh via login script

## Project Structure

```text
Kite_App_Main/
├── app.py
├── requirements.txt
├── README.md
├── Auth/
│   └── login.py
├── Core/
│   ├── Delta_IV.py
│   ├── Monitor.py
│   ├── Kill_Time.py
│   ├── shared_resources.py
│   └── system_close.py
├── Cred/
│   ├── Cred_kite_PREM.ini
│   ├── Cred_kite.ini
│   └── access_token.txt
├── static/
│   ├── script.js
│   └── styles.css
└── templates/
    └── index.html
```

## Requirements

- Python 3.10+
- Zerodha Kite API credentials
- Chrome/Chromium-compatible browser (for Selenium login flow)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create/update the credential files in `Cred/`:

- `Cred/Cred_kite_PREM.ini` (used by app runtime)
- `Cred/Cred_kite.ini` (used by kill-time flow)

Expected INI structure:

```ini
[Kite]
api_key=your_api_key
api_secret=your_api_secret
user_id=your_user_id
password=your_password
totp_secret=your_totp_secret
```

Access token file:

- `Cred/access_token.txt`

If token is invalid/expired, the app triggers `Auth/login.py` to refresh it.

## Run

```bash
python app.py
```

App starts on:

- `http://127.0.0.1:5000`

## API Endpoints

- `GET /` -> Dashboard UI
- `GET /option_data` -> Option chain and strategy metrics
- `GET /pnl` -> Current P&L snapshot
- `POST /manual_exit` -> Triggers background manual exit

## Notes

- This project executes real trading account actions through Kite APIs.
- Use with caution and validate all logic in a safe environment first.
- Keep `Cred/` files private and never commit secrets.

## Disclaimer

This repository is for educational/personal automation use. It is not financial advice.
