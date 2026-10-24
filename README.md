# BrightCore Careers

A recruitment website where people can find jobs and apply. Admins can post jobs and manage applications.

## Run the app

You need Docker Desktop running on Windows or macOS, or Docker Engine with Docker Compose on Linux.

In the project folder, run:

```sh
docker compose up --build -d
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

To stop the app, run:

```sh
docker compose down
```

The database and uploaded CVs are kept in a Docker volume when you stop the app. Running `docker compose down -v` deletes that saved data.

## Admin login

On a new database, use:

- Username: `admin`
- Password: `BrightCore2026!`

Choose **Team login** on the website. The sample jobs and admin account are created the first time the app starts with an empty database.

## What the app includes

- A public jobs page with search and job details.
- An application form with server-side validation and PDF CV uploads up to 5 MB.
- Checks that prevent applications to closed or expired jobs, and duplicate applications to the same job using the same email address.
- An admin area to create, edit, and close jobs; filter and review applications; download CVs; and accept or reject applicants.
- An overview of application counts by job and status.
- Three sample jobs created when the database is empty.
- Optional applicant email notifications when an application is accepted or rejected. SMTP settings are needed to send real email.

## Technology

- Python's standard library runs the web server, so no Python packages need to be installed.
- SQLite stores jobs and applications.
- HTML, CSS, and JavaScript build the website and admin pages.
- Docker Compose runs the app and keeps its data between restarts.

Passwords are stored as hashes. Admin pages are protected, database queries use parameters, and CVs are served through admin-only routes.

## Assumptions

- The app starts with one admin account and does not have public admin registration or password reset.
- Sample jobs are added only to an empty database.
- An applicant can apply once to each job with the same email address.
- Cover notes are optional.
- Email is optional; an application status is saved even if an email cannot be sent.

## Tests

Run the automated tests with Python 3.10 or later:

```sh
python -m unittest discover -s tests -v
```

## Improvements I would make with more time

- Add CSRF protection for admin forms.
- Let admins change their passwords and manage admin accounts.
- Add pages to make large applicant lists easier to browse.
- Keep a more complete record of admin actions.
- Use an email provider that works on free hosting plans.
- Store uploaded CVs in managed file storage.
