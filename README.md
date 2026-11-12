# Freshie CoinTracker (Django + FastAPI)

Live crypto prices from the CoinGecko API, with:

- **Django**: admin panel, users, ORM/migrations, dashboard page
- **FastAPI** (mounted at `/api`): async REST endpoints and a WebSocket price feed
- **Background poller**: fetches prices every `POLL_INTERVAL` seconds, stores history, fires price alerts

Both frameworks run in one ASGI process (`config/asgi.py`): FastAPI is the outer app and Django is mounted at `/`.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

python manage.py migrate
python manage.py createsuperuser

uvicorn config.asgi:application --reload
```

Open:
- Dashboard: http://localhost:8000/
- Interactive API docs: http://localhost:8000/api/docs
- Admin: http://localhost:8000/admin/

> Use `uvicorn`, not `manage.py runserver`. The WebSocket feed and background poller need the ASGI server.

## API

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/prices?ids=bitcoin,ethereum&vs=usd` | no | Live prices |
| GET | `/api/prices/{coin_id}` | no | One coin |
| GET | `/api/prices/{coin_id}/history?limit=100` | no | Stored snapshots |
| WS | `/api/ws/prices` | no | Pushed price + alert updates |
| POST | `/api/auth/register` | no | Creates a user, returns `{token, recovery_phrase}` (12-word phrase shown once) |\n| POST | `/api/auth/recover` | no | `{username, recovery_phrase, new_password}` resets a password |\n| GET | `/api/coins?page=1&per_page=100` | no | Paginated live prices for the CoinGecko catalogue; add `q=` to search |
| POST | `/api/auth/token` | no | `{username, password}` returns `{token}` |
| GET/POST | `/api/watchlist` | Bearer | List / add `{coin_id}` |
| DELETE | `/api/watchlist/{coin_id}` | Bearer | Remove |
| GET/POST | `/api/alerts` | Bearer | List / create `{coin_id, direction: above\|below, target_price}` |
| DELETE | `/api/alerts/{id}` | Bearer | Delete |
| GET | `/api/portfolio` | Bearer | Your holdings with live value and profit/loss |
| PUT | `/api/portfolio` | Bearer | Create/replace a position `{coin_id, amount, avg_buy_price}` |
| DELETE | `/api/portfolio/{coin_id}` | Bearer | Remove a position |

Coin ids are CoinGecko ids (`bitcoin`, `ethereum`, `solana`...). Full list: https://api.coingecko.com/api/v3/coins/list

Example:
```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/token -H 'content-type: application/json' \
  -d '{"username":"admin","password":"yourpassword"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -X POST localhost:8000/api/alerts -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"coin_id":"bitcoin","direction":"above","target_price":100000}'
```

## Tests and maintenance

```bash
python manage.py test                 # models, alert logic, price parsing, portfolio P&L
python manage.py prune_snapshots --days 7   # delete old price history (run daily via cron)
```

Set `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` in `.env` (and `pip install "psycopg[binary]"`) to use PostgreSQL instead of SQLite.

## Project layout

```
config/       Django settings, urls, asgi.py (FastAPI + Django wiring)
market/       Django app: models, admin, dashboard view + template
api/          FastAPI app: routes, schemas, auth dependency,
              price_client.py (CoinGecko), poller.py (background task + WebSocket hub),
              portfolio.py (valuation / P&L)
```

## Notes for going further

- **Production:** switch `DATABASES` to PostgreSQL, set `DJANGO_DEBUG=0`, a real `DJANGO_SECRET_KEY`, and run `uvicorn` behind nginx/Caddy with HTTPS (needed for `wss://`).
- **Snapshots grow quickly** (one row per coin per poll). Run `prune_snapshots` on a schedule or lengthen `POLL_INTERVAL`.
- **Rate limits:** CoinGecko's free tier is limited. A free Demo API key in `COINGECKO_API_KEY` raises the limit; responses are cached for `PRICE_CACHE_TTL` seconds.
- **Scaling out:** the WebSocket hub and poller are in-process. With several workers, move broadcasting to Redis pub/sub and run the poller as a single separate worker (Celery beat or a dedicated process).
- **Prices are for information only.** If you add trading or custody later, keep money in `Decimal`, use a ledger, and never store private keys in the database.
