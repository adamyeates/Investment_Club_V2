"""Settings, read from environment variables (or a .env file next to this project)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader so we don't need python-dotenv. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Where the data comes from: "sheets_api" (recommended), "csv" (publish-to-web links),
# or "xlsx" (a local export, handy for development without Google credentials).
SOURCE = os.environ.get("SOURCE", "sheets_api").strip().lower()

# --- sheets_api source ---
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", str(ROOT / "service_account.json"))

# --- csv source (File > Share > Publish to web, one link per tab, CSV format) ---
PORTFOLIO_CSV_URL = os.environ.get("PORTFOLIO_CSV_URL", "")
TRANSACTIONS_CSV_URL = os.environ.get("TRANSACTIONS_CSV_URL", "")

# --- xlsx source ---
XLSX_PATH = os.environ.get("XLSX_PATH", "")

# Tab names in the Google Sheet
PORTFOLIO_TAB = os.environ.get("PORTFOLIO_TAB", "2025 Portfolio")
TRANSACTIONS_TAB = os.environ.get("TRANSACTIONS_TAB", "Transactions")

# Re-read the sheet this often so GOOGLEFINANCE price moves reach the site.
POLL_SECONDS = max(15, _int("POLL_SECONDS", 60))
# After the Apps Script webhook fires, wait this long so a newly typed ticker's
# GOOGLEFINANCE formula has time to calculate before we read it.
WEBHOOK_DELAY_SECONDS = max(0, _int("WEBHOOK_DELAY_SECONDS", 3))
# Shared secret the Apps Script sends; requests without it are rejected.
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# Comma-separated list of sites allowed to call the API from a browser
# (only needed if index.html is hosted somewhere other than this server).
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

# Rows whose ticker is one of these are treated as cash (no shares / cost / return shown).
CASH_TICKERS = {t.strip().upper() for t in os.environ.get("CASH_TICKERS", "CASH,VUSXX").split(",") if t.strip()}

FRONTEND_FILE = ROOT / "frontend" / "index.html"
