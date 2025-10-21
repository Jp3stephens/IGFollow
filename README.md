# IGFollow Tracker

IGFollow Tracker is a Flask web application that helps you monitor how an Instagram account's follower and following lists change over time. Upload CSV exports directly from Instagram, store historical snapshots in a secure database, and compare changes to understand who followed, unfollowed, or potentially blocked an account.

> **Important:** IGFollow Tracker does not automate data collection from Instagram. You must download follower/following lists using Instagram's official "Download your information" tool and upload the CSV files manually.

## Features

- Landing page, authentication, and dashboard for managing tracked accounts.
- Upload follower or following CSV exports (username/full_name columns supported).
- Store each snapshot in a relational database for long-term comparison.
- Automatically compute differences between the latest two snapshots.
- Export the newest snapshot to CSV or Excel.
- Paywall guard that requires a subscription for exports larger than 600 profiles (configurable via `MAX_FREE_EXPORT`).

## Tech Stack

- Python 3.11+
- Flask, SQLAlchemy, Flask-Login, Flask-Migrate
- SQLite (default) with the option to point at any SQLAlchemy-compatible database via `DATABASE_URL`.

## Getting Started

### 1. Clone and install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file (optional) to override defaults:

```
SECRET_KEY=change-me
SECURITY_PASSWORD_SALT=change-me-too
DATABASE_URL=sqlite:///instance/igfollow.db
MAX_FREE_EXPORT=600
```

### 3. Initialize the database

```bash
flask --app run.py db init
flask --app run.py db migrate -m "Initial tables"
flask --app run.py db upgrade
```

These commands create the user, tracked account, snapshot, and snapshot entry tables.

### 4. Run the application

```bash
flask --app run.py run --debug
```

Visit [http://127.0.0.1:5000](http://127.0.0.1:5000) to access the landing page and sign up.

## Usage Workflow

1. Register or log in.
2. Add an Instagram handle to track.
3. Upload follower and following CSV files (use Instagram's data download).
4. Re-upload new exports whenever you want to compare changes.
5. Review the difference report on the account detail page.
6. Export the latest snapshot as CSV/Excel; upgrade if you exceed the free plan limit.

## Paywall & Subscription Logic

Users on the free plan can track unlimited accounts but exporting any list with more than 600 rows triggers the paywall page. To unlock unlimited exports, set `is_subscribed=True` directly in the database or build your own payment integration on top of the provided structure.

## Deployment

IGFollow Tracker is production ready for platforms such as Render, Railway, Fly.io, or any container-based host.

1. Set `FLASK_ENV=production` and configure secure `SECRET_KEY` & database credentials.
2. Run migrations on the production database.
3. Serve with a production WSGI server such as Gunicorn:

```bash
gunicorn 'run:app'
```

## Testing

A minimal test suite is provided for core diff logic. Run with:

```bash
pytest
```

## Roadmap

- Automated Instagram data fetching via approved APIs.
- Email notifications and scheduled comparisons.
- Subscription billing integration.

## License

MIT
