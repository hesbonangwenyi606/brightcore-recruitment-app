# BrightCore Careers

A small, responsive recruitment app for public job listings and candidate applications, with a private admin dashboard for hiring teams.

## Run locally

Requires Python 3.10 or later. There are no third-party packages to install.

```bash
python server.py
```

Open [http://localhost:8000](http://localhost:8000). The app creates its SQLite database and three sample roles on first run. Data persists in `brightcore.sqlite3`; candidate CVs are stored in `private_uploads/`, outside the public routes.

Seeded admin login: **admin** / **BrightCore2026!**. Set `ADMIN_PASSWORD` before first launch to choose a different initial password. Set `PORT`, `BRIGHTCORE_DB`, or `BRIGHTCORE_UPLOADS` to customize the port and storage locations.

## Run with Docker

Requires Docker Engine with the Compose plugin. To use a custom admin password or configure applicant email, copy `.env.example` to `.env` and edit it first. Then run:

```bash
docker compose up --build -d
```

Open [http://localhost:8000](http://localhost:8000). The database and private CV uploads persist in the `brightcore_data` Docker volume. To stop the app while keeping its data, run `docker compose down`; to remove the saved data too, run `docker compose down -v`.

## Applicant email notifications

The app sends the saved acceptance or rejection message when an admin changes an application to **Accepted** or **Rejected**. Configure SMTP before starting the server: copy `.env.example` to `.env` and enter your mail provider's SMTP settings. The app reads `.env` automatically and uses STARTTLS by default. For SSL SMTP (usually port 465), set `SMTP_USE_SSL=true` and `SMTP_STARTTLS=false`. Keep `.env` private; it is ignored by Git. A successful email is sent once for each status transition. If SMTP is not configured or delivery fails, the application update is still saved and the admin sees a notice.

## Technology choices

- Python standard library HTTP server keeps setup to one command and avoids third-party runtime dependencies.
- SQLite provides a persistent relational store, uniqueness constraints for duplicate applications, and parameterized queries.
- Plain HTML, CSS and JavaScript provide a lightweight responsive candidate site and admin dashboard without a frontend build step.
- Admin passwords use salted PBKDF2-HMAC-SHA256. Session cookies are HTTP-only and SameSite strict. CVs are checked for PDF signature and size and can only be downloaded through an authenticated admin endpoint.

## Assumptions

- The seeded admin account is sufficient for this small take-home; there is no public admin registration or password reset.
- The cover note is optional. Each application is unique by normalized email address and job.
- Closing a role stops new applications while preserving its existing applications.
- Status changes are recorded on the application; notes are visible to the hiring team.
- This app is intended for local demonstration. Production deployment should run behind HTTPS and use a durable session store and managed file storage.

## Tests

Run the standard-library integration tests with:

```bash
python -m unittest discover -s tests -v
```

They cover password hashing, admin route protection, public closed-job filtering, and duplicate application rejection.

## With more time

Add CSRF tokens, configurable admin accounts and password rotation, richer applicant search and pagination, and production deployment configuration with HTTPS, persistent sessions, and a managed private file store.
