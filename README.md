# BrightCore Careers

A responsive recruitment app for browsing open roles, submitting applications with a PDF CV, and managing candidates through a private hiring dashboard.

## Run with Docker Compose

Requires Docker Desktop on Windows/macOS, or Docker Engine and the Compose plugin on Linux. Start Docker Desktop first on Windows.

From the project directory, run:

```sh
docker compose up --build -d
```

Open [http://localhost:8000](http://localhost:8000). To follow the server logs, run `docker compose logs -f`. Stop the app with `docker compose down`.

Compose stores the SQLite database and private CV uploads in the `brightcore_data` named volume, so they remain when the container is stopped or recreated. `docker compose down -v` also deletes that saved data.

To change the initial admin password or configure email, copy `.env.example` to `.env` and edit it before the first start. Keep `.env` private; it is ignored by Git. `PORT` changes the host port (for example, `PORT=8080` maps the app to `http://localhost:8080`).

## Run locally without Docker

Requires Python 3.10 or later. The app uses only the Python standard library.

```sh
python server.py
```

Open [http://localhost:8000](http://localhost:8000). Stop the server with **Ctrl+C**. The local database is `brightcore.sqlite3`, and uploaded CVs are stored in `private_uploads/`. Both paths can be changed with `BRIGHTCORE_DB` and `BRIGHTCORE_UPLOADS`; use `PORT` to change the listening port.

## Admin login

- Username: `admin`
- Password: `BrightCore2026!`

This seeded demo account is created on the first run only. Set `ADMIN_PASSWORD` before first startup to choose a different password. If the database already exists, changing this variable does not change the existing admin password.

## Seed data and features

On first startup, the app seeds three sample roles if there are no jobs in the database:

- Senior Product Designer — Nairobi, Kenya
- Backend Engineer — Remote · East Africa
- People Operations Associate — Nairobi, Kenya

Candidates can search open roles by title, location, employment type, or job description and submit one application per job and email address. Applications require a PDF CV of up to 10 MB. The private dashboard supports job management, applicant review, status changes, and filtering applications by status.

## Applicant email notifications

When an admin changes an application to **Accepted** or **Rejected**, the app sends the saved message to the applicant. Configure SMTP in `.env` before starting the app. STARTTLS on port 587 is the default; for SSL SMTP (commonly port 465), set `SMTP_USE_SSL=true` and `SMTP_STARTTLS=false`. For Gmail, use an App Password rather than the account's regular password.

The status update is saved even if email is not configured or delivery fails; the admin dashboard displays a notice. Set `EMAIL_DRY_RUN=true` to log the message instead of sending it.

## Technology choices

- **Python standard library HTTP server:** keeps setup simple and avoids runtime package installation for this small app.
- **SQLite:** provides a persistent relational database, uniqueness constraints for duplicate applications, and parameterized queries without a separate database service.
- **HTML, CSS, and JavaScript:** deliver a responsive site and dashboard without a frontend build step.
- **Docker Compose and a named volume:** provide a repeatable container launch and persistent database/CV storage.
- **Security basics:** admin passwords use salted PBKDF2-HMAC-SHA256; session cookies are HTTP-only and SameSite strict; uploaded CVs are checked for PDF signature and size and are only served through an authenticated admin route.

## Assumptions

- This is a local demonstration/take-home app. It has one seeded admin and no public admin registration or password reset.
- Cover notes are optional; duplicate applications are prevented by normalized email address and job.
- Closing a job prevents new applications while preserving its existing applications.
- Applicants are notified only when an admin changes their status to Accepted or Rejected. SMTP is optional.
- Local files and SQLite are sufficient for a demo; a production deployment would need HTTPS and durable managed storage/session handling.

## Tests

Run the standard-library integration tests with:

```sh
python -m unittest discover -s tests -v
```

The tests cover password hashing, admin route protection, the sample jobs, the public job search control, filtering of closed jobs, and duplicate application rejection. GitHub Actions runs the integration tests, validates Compose configuration, and builds the Docker image on pushes and pull requests to `main`.

## Improvements with more time

Add CSRF protection, configurable admin accounts and password rotation, richer applicant search and pagination, stronger production deployment settings, and managed storage for uploaded files.
