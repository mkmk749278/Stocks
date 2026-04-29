# AXIOM — Indian Stock Market Signal Engine

Production signal engine for **NSE / BSE only**. No crypto. No forex. No
international markets. SEBI-regulated India equity, F&O, MCX, and NSE
currency segments. Market hours 9:15 AM – 3:30 PM IST, signal cutoff 3:20 PM.

## What this commit ships

This is the foundation commit on `claude/axiom-signal-engine-QpEa6`.

- **Backend**: FastAPI + Celery + Redis + Postgres (async SQLAlchemy 2.x).
- **9-layer signal architecture** with a single `Layer` ABC and weighted
  aggregator that fires only when ≥3 layers agree within a 60-second window.
- **Layer 1 — Order Flow**: full implementation. Cumulative Delta (CVD),
  absorption detection, footprint imbalance, VWAP deviation z-score, with a
  per-layer backtest harness.
- **Layers 2–9**: registered stubs raising `NotImplementedError`. Each lands
  on its own branch with full tests + backtest.
- **Feed**: Zerodha Kite WebSocket (`kiteconnect`) with auto-reconnect and a
  deterministic `ReplayFeed` for tests/backtests.
- **Bot**: Telegram bot stub (`/start`, `/status`, `/plan`).
- **CI/CD**: `deploy.yml` (push→main), `apk-release.yml` (tag `v*.*.*`),
  `model-validate.yml` (path-filtered to ML layer + backtest harness, fails
  PR on Win Rate ≤ 58%, PF ≤ 1.5, Sharpe ≤ 1.5, MaxDD ≥ 20%).
- **Infra**: supervisor configs (api, worker, beat, feed), nginx reverse
  proxy, alembic migration, docker-compose for local Postgres/Redis only.

## Layout

```
app/
  config.py        logger.py     timeutil.py     crypto.py
  db.py            redis_client.py               celery_app.py
  main.py          api/          telegram/
  feed/            base.py  kite_ws.py  replay.py  __main__.py
  signals/         base.py  registry.py  aggregator.py  publisher.py  risk.py  backtest.py
                   layers/  l1_order_flow.py (full) + l2..l9 (stubs)
  models/          schemas/      tasks/          tests/
alembic/   .github/workflows/   nginx/   supervisor/   scripts/
```

## Bring-up (VPS, Ubuntu)

```bash
sudo apt install -y python3.11 python3.11-venv postgresql-16 redis-server nginx supervisor
sudo adduser --system --group axiom
sudo mkdir -p /opt/axiom /var/log/axiom
sudo chown axiom:axiom /opt/axiom /var/log/axiom

sudo -u axiom git clone https://github.com/mkmk749278/Stocks.git /opt/axiom/app
sudo -u axiom python3.11 -m venv /opt/axiom/venv
sudo -u axiom /opt/axiom/venv/bin/pip install -r /opt/axiom/app/requirements.txt

sudo -u axiom cp /opt/axiom/app/.env.example /opt/axiom/app/.env
sudo -u axiom nano /opt/axiom/app/.env          # fill secrets

sudo -u axiom /opt/axiom/venv/bin/alembic -c /opt/axiom/app/alembic.ini upgrade head
sudo -u axiom /opt/axiom/venv/bin/python -m scripts.seed_universe

sudo cp /opt/axiom/app/supervisor/*.conf /etc/supervisor/conf.d/
sudo supervisorctl reread && sudo supervisorctl update

sudo cp /opt/axiom/app/nginx/axiom.conf /etc/nginx/sites-available/axiom
sudo ln -sf /etc/nginx/sites-available/axiom /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Smoke checks

```bash
pytest -q                                  # 19/19 green
curl -s http://127.0.0.1:8000/health       # status, ist_now, market_open
sudo supervisorctl status                  # axiom-api, -worker, -beat, -feed RUNNING
```

## Owner workflow (Termux on Android)

```bash
nano <file>.py
git add . && git commit -m "..."
git push origin claude/axiom-signal-engine-QpEa6
# After review, fast-forward to main → deploy.yml runs.
```

## Plans

| Plan    | Price       | Access                                       |
|---------|-------------|----------------------------------------------|
| Free    | ₹0          | Delayed signals (lead gen)                   |
| Basic   | ₹999/mo     | Equity signals via Telegram                  |
| Premium | ₹2,999/mo   | F&O signals + App + Telegram                 |
| Elite   | ₹7,999/mo   | Auto-trade + all segments                    |

## Next branch

`claude/axiom-l2-volume-profile` — VPOC, VAH, VAL, HVN, LVN.
