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
| POST | `/api/auth/register` | no | `{username, password, email?}` creates a user, returns `{token, username}` |
| POST | `/api/auth/token` | no | `{username, password}` returns `{token, username}` |
| GET | `/api/auth/me` | Bearer | Current user profile `{id, username, email}` |
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


## Recent implementation update

- Registration now requires an email address and sends a welcome notification.
- Added email password recovery: request a 6-digit code, then reset the password. Codes are hashed, expire after `PASSWORD_RESET_CODE_MINUTES`, are single-use, and are locked after five failed attempts.
- Added market browsing from CoinGecko's paginated coin catalogue, remote search, and USD/NGN market quote selection.
- Configure SMTP variables in `.env` for actual email delivery. With the console email backend, messages are printed in the server terminal for local testing.
- Run `python manage.py migrate` after pulling these changes.

## Real-money trading integration status

This project includes a ledger-based internal wallet and Paystack NGN payment adapter, but it is not itself a licensed exchange, broker, payment institution, or cryptocurrency custodian. External money movement remains disabled by default. Do not represent manual portfolio edits as purchases. Production operation requires all applicable authorisations and provider approvals, KYC/AML and transaction monitoring, operational reconciliation, and customer-asset safeguarding. Configure credentials only in server environment variables or a secrets manager. Never expose secret keys in frontend code.

## Wallet and payment integration status

The wallet backend now uses a double-entry ledger for NGN and USD wallet balances. It includes:

- Wallet balance and transaction-history endpoints (`GET /api/wallets`, `GET /api/wallets/transactions`).
- Internal user-to-user transfers in NGN or USD (`POST /api/wallets/transfer`). Both sides are posted in one database transaction; the sender cannot transfer more than the available ledger balance.
- Paystack NGN payment initialization (`POST /api/wallets/deposit`) and a signed webhook at `/api/payments/paystack/webhook`. The webhook verifies the payment with Paystack before posting the credit and uses the payment reference for idempotency.
- Paystack NGN bank withdrawal initiation (`POST /api/wallets/withdraw`), including bank-account name resolution, ledger reservation and webhook settlement/refund handling. Ambiguous provider timeouts remain pending for reconciliation rather than being automatically refunded, to avoid double-spending if Paystack accepted a transfer but the response was lost.

### Important production gates

`PAYMENTS_ENABLED=0` is the default. Do not switch it to `1` until the Nigerian business has completed Paystack onboarding/go-live, the webhook URL is deployed over HTTPS, webhook events are tested, and the business has sufficient Paystack transfer balance. Set `PAYSTACK_SECRET_KEY` and the current `PAYSTACK_WEBHOOK_SECRET` (the `whsec_` signing secret) only in the server environment or secret manager; never commit them or expose them in frontend JavaScript. The webhook supports Paystack’s timestamped `Paystack-Signature` and legacy `x-paystack-signature` header formats. Configure the webhook URL in Paystack as `https://YOUR-DOMAIN/api/payments/paystack/webhook`.

Paystack DVA account creation endpoints are present but fail closed until registered-business go-live and the applicable customer-validation requirements are approved; the current checkout deposit flow uses Paystack transaction initialization and verified `charge.success` events. USD deposits/withdrawals are not connected to a provider. USD wallet balances can currently be used for internal transfers only.

### Luno and real crypto trading

Luno has not yet been wired into live order execution in this code. Its API supports order placement, account access, sends and withdrawals, but an API key is authority over the Luno account to which it belongs; a single platform key must not be treated as segregated customer custody. For this reason, real buy/sell execution and on-chain crypto withdrawals remain deliberately disabled. The project needs an approved custody/agency architecture, customer-level account allocation, reconciliation, KYC/AML controls, withdrawal risk checks, and applicable Nigerian regulatory approvals before these endpoints can be enabled. The current `/api/trades` endpoint returns HTTP 503 rather than pretending a portfolio edit is a real trade.

The existing manual portfolio endpoints remain for portfolio tracking only. They do not create real crypto positions or execute orders.

### New migration

After extracting the project, run:

```powershell
python manage.py migrate
```

For local development, leave `PAYMENTS_ENABLED=0`. Transfers between existing registered users work against the internal ledger; external payment rails stay disabled until the business credentials and approval are ready.


Luno was reported by Nigeria’s SEC as admitted to the ARIP programme in July 2026 with Approval-in-Principle. An AIP is not a final licence. Confirm Luno’s current authorisation and the platform operator’s own obligations with Nigerian counsel and the SEC before enabling customer trading or custody.


## Additional provider integration scaffolding (fail-closed)

The following endpoints and models have been added while keeping all external money movement disabled by default:

- `GET /api/wallets/ngn/virtual-account`: returns the user's assigned Paystack NGN virtual account, if one exists.
- `POST /api/wallets/ngn/virtual-account`: accepts first name, last name, phone, preferred bank and explicit consent. Live account assignment requires `BUSINESS_REGISTERED=1`, `PAYSTACK_DVA_ENABLED=1`, and `PAYSTACK_DVA_VALIDATION_REQUIRED=0`. For sandbox-only testing, `PAYSTACK_DVA_TEST_MODE=1` is accepted only when `PAYSTACK_SECRET_KEY` begins with `sk_test_`; it forces Paystack’s documented `test-bank` and cannot be used with live keys. The validation flag defaults to `1` because financial-services businesses may be required by Paystack to validate customer identity before assigning a live DVA. This endpoint does not collect or store BVN.
- `POST /api/wallets/usd/deposit` and `POST /api/wallets/usd/withdraw`: defined fail-closed endpoints. They do not accept or credit funds until an eligible provider adapter, settlement route and compliance approval are configured.
- `GET /api/trading/status`: reports whether Luno credentials and approval flags are present without revealing credentials.
- `POST /api/trades`: now accepts a typed buy/sell request but remains disabled until Luno Business approval and a segregated customer-custody architecture is certified.

### Provider eligibility is a real blocker

Paystack's current published international-payments eligibility list explicitly excludes cryptocurrency businesses and mobile-wallet businesses. Therefore CryptoTracker must not use Paystack international card processing as the USD wallet funding route. Paystack's USD card collection/settlement availability for other eligible Nigerian businesses does not override this exclusion. USD bank transfers and USD payouts also need a separately approved provider and a verified settlement account. Do not enable USD payments by setting an environment flag alone.

Paystack Dedicated Virtual Accounts are available only to registered businesses that have completed go-live. Financial-services businesses may need to validate customers before creating accounts. The DVA endpoint is therefore disabled until the business is registered and Paystack has approved the DVA use case and identity-validation process. Use `test-bank` only with Paystack test credentials after the required test configuration is available.

Luno's business-account guidance says that businesses buying, selling or storing third-party customer funds must demonstrate the relevant licences and provide AML/ATF/KYC policies. A business application has not yet been made, so no Luno orders are submitted.

Never set the approval flags to `1` merely to bypass these requirements. API keys must be stored only in server environment variables or a secrets manager.

## User profile

Signed-in users can open `/profile/` from the dashboard to save their first name, surname, phone number and gender. The profile API (`GET /api/profile`, `PUT /api/profile`) is authenticated with the existing CryptoTracker bearer token. Names are stored on the Django user record; phone number and gender are stored in the one-to-one `UserProfile` model. Apply the new migration with `python manage.py migrate`.
