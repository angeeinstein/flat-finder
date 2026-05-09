# flat-finder

A self-hosted web application for collecting, archiving, comparing, rating, and
managing apartment listings from external real-estate websites.

You paste listing URLs (e.g. willhaben.at). The server fetches and stores the
relevant info, downloads and archives photos, extracts structured details,
detects duplicates, shows everything in a comparable dashboard, plots them on a
map, calculates travel times to your target addresses (TU Wien, your office,
etc.), and lets you rate each apartment with customizable categories.

It is designed to install directly on a Linux server with a single shell
script — **no Docker required**.

---

## Features

- **Login & user management** with admin role, first-admin setup, audit log,
  login rate limiting, CSRF protection
- **Import via URL paste** — modular importer (Willhaben + generic JSON-LD/OG
  fallback). All outbound fetches go through an SSRF-safe HTTP client
- **Archives everything** — downloads photos, generates thumbnails, stores
  text & HTML snapshots so listings stay viewable even after the source is gone
- **Apartment vs ListingSource** — the same physical apartment can be linked
  to multiple external URLs (deduplication preserves history)
- **Duplicate detection** — multi-signal confidence score from URL/external
  ID, address, coordinates, price, area, rooms, title similarity, contact,
  and image perceptual hashes
- **Rating system** — admin defines weighted categories, users rate per
  category with comments; weighted score normalized to 0–100; per-user and
  cross-user averages
- **Status, notes, tags** per user per apartment
- **Travel times** to global and per-user target addresses, multiple modes
  (walk/bike/car/transit), pluggable provider (mock / OSRM / OpenRouteService)
- **Interactive map** (Leaflet) with marker color modes (score/price/status/
  travel time), filter-aware popups, target markers
- **Comparison view** for up to four apartments side-by-side
- **Warning flags** (missing address, no photos, high deposit, geocoding
  failed, …) shown as badges on dashboard and detail page
- **Modern responsive UI** — Bootstrap 5, mobile-first cards on phone and a
  compact table on desktop

---

## Requirements

- A Linux server: **Debian 12** or **Ubuntu 22.04 / 24.04**
- Root or sudo access
- 1 GB RAM, ~5 GB disk for a small private install
- Open port 80 (and 443 if you want HTTPS)

The installer pulls in everything else automatically:
PostgreSQL, Redis, Nginx, Python 3, Gunicorn, RQ, build toolchain.

---

## Bare-metal install (recommended)

On a fresh Debian/Ubuntu server:

```bash
curl -fsSL https://raw.githubusercontent.com/angeeinstein/flat-finder/main/install.sh | sudo bash
```

The installer will:

1. Install required system packages
2. Create the `flatfinder` system user
3. Create directories under `/opt/flat-finder`, `/etc/flat-finder`,
   `/var/lib/flat-finder`, and `/var/log/flat-finder`
4. Clone this repo
5. Create a Python virtualenv and install dependencies
6. Generate `/etc/flat-finder/flat-finder.env` with random secrets
7. Provision the PostgreSQL database and user
8. Run database migrations
9. Install systemd units `flat-finder-web.service` and
   `flat-finder-worker.service`
10. Configure Nginx as a reverse proxy
11. Optionally request a Let's Encrypt certificate via `certbot`

When it finishes, open `http://your-server` in a browser and complete the
**first-admin setup** form. From then on, the app requires login.

### Manual install

If you prefer to install by hand:

```bash
sudo apt-get install -y git python3 python3-venv python3-pip python3-dev \
    build-essential libpq-dev postgresql postgresql-contrib redis-server nginx
sudo adduser --system --group flatfinder
sudo mkdir -p /opt/flat-finder /etc/flat-finder /var/lib/flat-finder/{images,snapshots,backups} /var/log/flat-finder
sudo chown -R flatfinder:flatfinder /opt/flat-finder /var/lib/flat-finder /var/log/flat-finder
sudo -u flatfinder git clone https://github.com/angeeinstein/flat-finder /opt/flat-finder
cd /opt/flat-finder
sudo -u flatfinder python3 -m venv venv
sudo -u flatfinder venv/bin/pip install -r requirements.txt

# Database
sudo -u postgres createuser flatfinder
sudo -u postgres createdb -O flatfinder flatfinder
sudo -u postgres psql -c "ALTER USER flatfinder WITH PASSWORD '...'"

# Config
sudo cp .env.example /etc/flat-finder/flat-finder.env
sudo chown root:flatfinder /etc/flat-finder/flat-finder.env
sudo chmod 0640 /etc/flat-finder/flat-finder.env
# Edit DATABASE_URL, FLASK_SECRET_KEY, etc.

# Migrations
cd /opt/flat-finder
sudo -u flatfinder bash -c "set -a; source /etc/flat-finder/flat-finder.env; set +a; venv/bin/flask db upgrade"

# systemd / nginx — render templates from deploy/ as the install.sh does.
```

---

## Updating

Re-run the installer; it auto-detects existing installs and shows a menu:

```bash
sudo bash /opt/flat-finder/install.sh
# pick "1) Update application"
```

Update flow:

1. Downloads the newest `install.sh` from GitHub
2. Replaces the local copy and re-executes
3. `git pull`s the application
4. Reinstalls Python dependencies
5. Runs new migrations
6. Restarts services

Your data, env file, and admin users are never touched.

---

## Backup and restore

From the installer menu:

- **10) Backup data** — writes a timestamped folder to
  `/var/lib/flat-finder/backups/<TIMESTAMP>/` containing
  `database.sql`, `flat-finder.env`, `images.tar.gz`, `snapshots.tar.gz`.
- **11) Restore backup** — asks for a backup directory, stops services,
  drops & recreates the DB, restores files, restarts services.

You can also run `pg_dump` manually:

```bash
PGPASSWORD=... pg_dump -U flatfinder flatfinder > backup.sql
tar -czf images.tar.gz -C /var/lib/flat-finder images
```

---

## Configuration

All runtime configuration lives in `/etc/flat-finder/flat-finder.env`.
The file is owned by `root:flatfinder` with mode `0640`, so the
`flatfinder` user can read it but other users cannot.

| Variable                         | Description                                                         |
|----------------------------------|---------------------------------------------------------------------|
| `FLASK_SECRET_KEY`               | Random secret key for sessions/CSRF (generated by installer)        |
| `DATABASE_URL`                   | `postgresql://user:pass@host:port/dbname`                           |
| `REDIS_URL`                      | `redis://localhost:6379/0`                                          |
| `APP_BASE_URL`                   | Public URL of the app (used in absolute links)                      |
| `DATA_DIR`, `IMAGE_DIR`, `SNAPSHOT_DIR` | Storage paths                                                |
| `MAX_IMPORT_DOWNLOAD_SIZE_MB`    | Max bytes downloaded per page fetch                                 |
| `MAX_IMAGE_DOWNLOAD_SIZE_MB`     | Max bytes per image                                                 |
| `IMPORT_HTTP_TIMEOUT`            | Per-request timeout in seconds                                      |
| `ROUTING_PROVIDER`               | `mock` (default) / `osrm` / `openrouteservice`                      |
| `OSRM_BASE_URL`                  | Base URL of OSRM, e.g. `https://router.project-osrm.org`            |
| `OPENROUTESERVICE_API_KEY`       | API key for ORS                                                     |
| `GEOCODING_PROVIDER`             | `nominatim` (default)                                               |
| `NOMINATIM_USER_AGENT`           | Required by Nominatim TOS                                           |
| `LOGIN_RATE_LIMIT`               | Flask-Limiter expression (default `10 per minute`)                  |
| `ALLOW_REGISTRATION`             | If true, anyone can register accounts (default false)               |
| `LOG_LEVEL`                      | `DEBUG`/`INFO`/`WARNING`                                            |

Restart the services after editing the env file:

```bash
sudo systemctl restart flat-finder-web flat-finder-worker
```

---

## systemd services

| Service                    | Purpose                                  |
|----------------------------|------------------------------------------|
| `flat-finder-web.service`     | Gunicorn bound to `127.0.0.1:8000`       |
| `flat-finder-worker.service`  | RQ worker for imports / refreshes        |

```bash
sudo systemctl status flat-finder-web
sudo systemctl status flat-finder-worker
sudo journalctl -u flat-finder-web -f
```

---

## Useful management commands

Run these as the `flatfinder` user (the installer does this for you):

```bash
sudo -u flatfinder /opt/flat-finder/venv/bin/flask check-config
sudo -u flatfinder /opt/flat-finder/venv/bin/flask create-admin
sudo -u flatfinder /opt/flat-finder/venv/bin/flask seed-demo
sudo -u flatfinder /opt/flat-finder/venv/bin/flask refresh-listings
sudo -u flatfinder /opt/flat-finder/venv/bin/flask recalc-travel-times
sudo -u flatfinder /opt/flat-finder/venv/bin/flask db upgrade
```

The env file is loaded automatically (`config.py` looks for
`/etc/flat-finder/flat-finder.env` first, then a local `.env`).

---

## Local development

```bash
git clone https://github.com/angeeinstein/flat-finder
cd flat-finder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

# Bring up Postgres + Redis on your host or run them however you like.
cp .env.example .env
# Edit .env with your DATABASE_URL and REDIS_URL.

export FLASK_APP=wsgi:app
export FLASK_ENV=development
flask db init      # only the first time
flask db migrate -m "initial"
flask db upgrade
flask seed-demo    # optional: sample data

flask run          # http://127.0.0.1:5000
# In another shell:
python worker.py   # RQ worker
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The default test database is in-memory SQLite. For tests that depend on
PostgreSQL features, set `TEST_DATABASE_URL`.

---

## Troubleshooting

**Web service won't start.** Run
`sudo journalctl -u flat-finder-web -n 200 --no-pager`. Common causes:
DB password mismatch (re-run installer option **9 - repair**), missing
migrations (option **7 - run migrations**).

**Imports never finish.** Check the worker:
`sudo systemctl status flat-finder-worker`. Make sure Redis is running:
`redis-cli ping`.

**Permission denied on /etc/flat-finder/flat-finder.env.**
The file is intentionally `0640` and group-readable only by `flatfinder`.
Run flask commands via `sudo -u flatfinder ...`.

**SSRF errors on legitimate URLs.** The validator rejects private/loopback/
link-local IPs. If you're trying to import from a local test server,
that won't work — start a real public URL.

---

## Security & legal notes

- The app is intended for **personal use** behind authentication.
- It is a defensive tool: it fetches public listing pages with a normal HTTP
  client, with size and redirect limits, blocking access to private/internal
  networks. It does **not** bypass CAPTCHAs, paywalls, or anti-bot systems.
- Respect the terms of service of every site you import from. Some platforms
  (including Willhaben) explicitly disallow scraping; only import URLs you
  are authorized to access. The author is not responsible for misuse.
- Image and snapshot archiving is a personal record-keeping feature; do not
  redistribute archived content publicly.

---

## License

MIT — see LICENSE file (add one if missing).
