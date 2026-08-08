# Manifest — Google Maps Business Scraper

A local tool with a FastAPI backend (runs the actual Playwright scraper as
background jobs) and a single-file HTML/CSS/JS frontend (no build step) that
shows results landing live as the scrape runs.

## ⚠️ Before you use this

Scraping Google Maps is against Google's Terms of Service. This is meant for
personal or low-volume research use — not commercial resale, and not
high-frequency/large-scale scraping (that's also what gets your IP rate
limited or blocked). For production or high-volume use, use the official
Google Places API instead.

## 1. Set up the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium

uvicorn main:app --reload --port 8000
```

Leave this running — it exposes the API at `http://localhost:8000`.

## 2. Open the frontend

Just open `frontend/index.html` directly in your browser (double-click it,
or `open frontend/index.html` / `start frontend/index.html`). No server or
build step needed — it's a static file that talks to the backend via
`fetch()`.

If your backend is running somewhere other than `http://localhost:8000`,
update the **Backend URL** field in the sidebar before starting a scan.

## 3. Use it

1. Enter a search query (e.g. `"cafes in Bandra, Mumbai"`) and a max listing
   count.
2. Click **Start scan**. The backend launches a headless Chromium browser,
   searches Google Maps, and scrapes each listing.
3. Rows appear in the manifest table live as they're scraped — you don't
   need to wait for the whole job to finish.
4. Click **Stop** anytime to end the job early and keep what's been
   collected so far.
5. Click **Export CSV** to download everything collected in that job.

## How it works

- `backend/scraper.py` — the Playwright scraping logic, with `on_result` /
  `on_status` callbacks so progress can be reported live.
- `backend/main.py` — FastAPI app. Each scan runs in a background thread and
  is tracked in an in-memory job store (`POST /api/jobs` to start,
  `GET /api/jobs/{id}` to poll, `GET /api/jobs/{id}/csv` to export).
- `frontend/index.html` — polls the job every ~1.2s and appends new rows to
  the table as they arrive.

## Notes & limits

- Job data is stored in memory — restarting the backend clears past jobs.
- This is a single-user local tool (no auth, no database) — don't expose
  the backend to the public internet as-is.
- Google's page structure changes periodically. If scraping stops returning
  data, the CSS selectors in `scraper.py` (`a.hfpxzc`, `div.F7nice`, etc.)
  are the first thing to check.
