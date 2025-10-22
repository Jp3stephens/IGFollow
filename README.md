# IGFollow Tracker

IGFollow Tracker is a Flask web application that keeps an Instagram account's follower and following lists in sync for you. Provide API credentials once, let the app pull the live rosters directly from Instagram, and review or export historical differences without managing spreadsheets by hand. Manual CSV/JSON uploads are still supported as a fallback when you want to ingest exports you've captured elsewhere.

## Features

- Landing page, authentication, and dashboard for managing tracked accounts.
- First-class Instagram API integration via [instagrapi](https://github.com/adw0rd/instagrapi) with automated follower/following syncs.
- Upload follower or following exports in CSV, JSON, or plain-text formats straight from Instagram's "Download your information" bundle whenever you need to backfill.
- Store each snapshot in a relational database for long-term comparison.
- Automatically compute differences between the latest two snapshots.
- Export the newest snapshot to CSV or Excel with a progress indicator and instant download trigger.
- Paywall guard that requires a subscription for exports larger than 600 profiles (configurable via `MAX_FREE_EXPORT`).
- Profile previews and avatars sourced straight from Instagram so every roster view feels tangible.

## Tech Stack

- Python 3.11+
- Flask, SQLAlchemy, Flask-Login, Flask-Migrate
- SQLite (default) with the option to point at any SQLAlchemy-compatible database via `DATABASE_URL`.

## Getting Started

### 1. Clone the repository

Use `git clone` with either the public repository URL or your fork:

```bash
git clone https://github.com/<your-org>/IGFollow.git
cd IGFollow
```

If you already initialized the project locally and just need the latest version, run `git pull` inside the project directory instead.

### 2. Create a virtual environment and install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file (optional) to override defaults:

```
SECRET_KEY=change-me
SECURITY_PASSWORD_SALT=change-me-too
DATABASE_URL=sqlite:///instance/igfollow.db
MAX_FREE_EXPORT=600
INSTAGRAM_USERNAME=your.api.account
INSTAGRAM_PASSWORD=your-strong-password
INSTAGRAM_FETCH_LIMIT=5000
INSTAGRAM_CACHE_MINUTES=10
```

> **Two-factor authentication:** If your Instagram account requires 2FA you will need to finish verification once by running the app locally; instagrapi caches the session in `instagrapi.json` within the working directory.

### 4. Initialize the database

```bash
flask --app run.py db init
flask --app run.py db migrate -m "Initial tables"
flask --app run.py db upgrade
```

These commands create the user, tracked account, snapshot, and snapshot entry tables (including Instagram profile metadata).

> Upgrading from an earlier clone? The app now auto-applies the latest SQLite column additions on startup, so simply rerunning
> the server will patch older local databases. `flask db upgrade` remains recommended for production or non-SQLite deployments.

### 5. Run the application

```bash
flask --app run.py run --debug
```

Visit [http://127.0.0.1:5000](http://127.0.0.1:5000) to access the landing page and sign up.

## Usage Workflow

1. Register or log in.
2. Add an Instagram handle to track. IGFollow will immediately sync the current followers/following lists via the API.
3. Review the account dashboard to see avatars, counts, and the latest diff summary.
4. Optional: Upload CSV/JSON/text exports if you want to import historical data.
5. Export the latest snapshot as CSV/Excel using the built-in progress bar; upgrade if you exceed the free plan limit.

## Paywall & Subscription Logic

Users on the free plan can track unlimited accounts but exporting any list with more than 600 rows triggers the paywall page. Free downloads include the first 600 entries; upgrade (toggle `is_subscribed=True` in the database while prototyping) for complete exports.

## Deployment

IGFollow Tracker is production ready for platforms such as Render, Railway, Fly.io, or any container-based host.

1. Set `FLASK_ENV=production` and configure secure `SECRET_KEY` & database credentials.
2. Run migrations on the production database.
3. Serve with a production WSGI server such as Gunicorn:

```bash
gunicorn 'run:app'
```

## Testing

The test suite covers diff logic, parsers, and an end-to-end happy path (including CSRF-protected requests). Run with:

```bash
pytest
```

## Roadmap

- Background jobs to refresh snapshots on a schedule.
- Email notifications whenever follower counts change dramatically.
- Subscription billing integration.

## License

MIT
