# BrightCore Careers

A responsive recruitment portal for BrightCore Technology Services. Candidates can browse and search open roles, read role details, and submit an application with a PDF CV. The hiring team can manage roles, review applications, download CVs, record notes, and update applicant status from a private dashboard.

## Run the app with Docker Compose

### Requirements

- Docker Desktop on Windows or macOS, or Docker Engine with the Compose plugin on Linux.
- On Windows, start Docker Desktop and wait until its engine is running before using Compose.

From the project directory, start the app with one command:

```sh
docker compose up --build -d
```

Open [http://localhost:8000](http://localhost:8000). The public careers page loads first; choose **Team login** in the top right to open the admin sign-in.

Useful commands:

```sh
docker compose logs -f       # Follow application logs
docker compose ps            # Check service status
docker compose down          # Stop and remove the container
```

Compose keeps the SQLite database and private CV uploads in the `brightcore_data` named volume. They survive a normal stop, rebuild, or container recreation. **`docker compose down -v` deletes this volume and all saved applications, jobs, and uploaded CVs.**

### Admin demo login

- Username: `admin`
- Password: `BrightCore2026!`

The demo admin and sample roles are created on the first run against an empty database. For a private local instance, set a different `ADMIN_PASSWORD` in `.env` before first startup. The password is only used when the admin account is first created; changing it later does not change the existing account. Keep `.env` private and never commit SMTP credentials.

### Optional configuration

Copy `.env.example` to `.env` and edit values before starting Compose. Email is optional; leave it unconfigured to run the app without sending mail. The Compose file reads `.env` automatically.

| Variable | Purpose | Default |
| --- | --- | --- |
| `PORT` | Host port mapped to the app (for example, `8080` opens `http://localhost:8080`) | `8000` |
| `ADMIN_PASSWORD` | Password used when creating the first admin account | `BrightCore2026!` |
| `SMTP_HOST` | SMTP server for applicant status messages | Empty (email disabled) |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP login credentials | Empty |
| `SMTP_FROM` | Sender email address | Empty |
| `SMTP_FROM_NAME` | Sender display name | `BrightCore Recruitment Team` |
| `SMTP_STARTTLS` | Use STARTTLS (typical for port 587) | `true` |
| `SMTP_USE_SSL` | Use implicit SSL (typical for port 465); turn off STARTTLS when enabled | `false` |
| `RESEND_API_KEY` | Resend API key; when set, the app sends mail through HTTPS instead of SMTP | Empty |
| `RESEND_FROM` | Sender address on a domain verified with Resend (for example, `BrightCore Recruitment <jobs@your-domain.com>`) | Empty |
| `EMAIL_DRY_RUN` | Log email content instead of sending it | `false` |

For Gmail SMTP, use a Google App Password as `SMTP_PASSWORD`, not your normal Google account password. When `RESEND_API_KEY` is set, the app uses the Resend HTTP API and requires `RESEND_FROM` to use a verified sending domain. The application still saves a status update if email is unavailable and displays a delivery notice in the dashboard.

## Run locally without Docker

Requires Python 3.10 or later. The application uses only the Python standard library; no package installation is needed.

```sh
python server.py
```

Open [http://localhost:8000](http://localhost:8000), then press **Ctrl+C** in the terminal to stop the server. The local database is `brightcore.sqlite3`; uploaded CVs are stored in `private_uploads/`. These paths can be changed with `BRIGHTCORE_DB` and `BRIGHTCORE_UPLOADS`. Set `PORT` to change the local server port. SMTP settings can also be supplied as environment variables when running outside Compose.

## Included features and sample data

When the database has no roles, the app creates three sample jobs:

- Senior Product Designer — Nairobi, Kenya — Full-time
- Backend Engineer — Remote · East Africa — Full-time
- People Operations Associate — Nairobi, Kenya — Contract

The careers page can search by role title, location, employment type, and job text. Candidates can submit one application per job and email address, with a required PDF CV up to 10 MB and an optional cover note. The private dashboard includes an overview, role management, applicant filtering by status, CV viewing and download, internal notes, and status decisions. Accepted and rejected decisions can send a customized message to the applicant once for each status decision.

## Email notifications

Applicant email is an optional extra. The message is sent when an admin saves an application as **Accepted** or **Rejected**. The app can use SMTP or the Resend HTTPS API; `RESEND_API_KEY` takes priority when configured. With `EMAIL_DRY_RUN=true`, the message is logged by the server for development instead of being sent. If sending fails, the status remains saved and the dashboard reports the email problem.

## Deploy to Render

The repository includes a Render Blueprint in `render.yaml`. It builds the Dockerfile, runs the service in Frankfurt, checks `/healthz`, and mounts a 1 GB persistent disk at `/data` for the database and CV uploads. The Blueprint asks you to provide `ADMIN_PASSWORD`; use a unique password and keep it private. For a free Render instance, use Supabase Postgres and private Storage as described in the Vercel setup below instead of the local SQLite database and disk. Render Free files are temporary, and the service sleeps when idle.

1. Push the project to GitHub, then sign in to Render and choose **New → Blueprint**.
2. Connect `hesbonangwenyi606/brightcore-recruitment-app` and select the `main` branch.
3. Review the Blueprint resources and costs. This service uses a paid web service plan because persistent disks are not available for free web services. Render bills compute and disk storage separately; check the [current Render pricing](https://render.com/pricing).
4. Set a unique `ADMIN_PASSWORD` when prompted and create the Blueprint. Choose Frankfurt for the service region if asked.
5. Wait for deployment to finish, open the `onrender.com` URL shown in the Render dashboard, and choose **Team login**. The username is `admin`; the password is the value you supplied for `ADMIN_PASSWORD`.

With the Blueprint, applications and uploaded CVs are stored on the persistent disk. The app uses SQLite and in-memory login sessions, so keep it as a single service instance; do not scale it to multiple instances. This deployment starts with a fresh database and the three sample jobs; it does not automatically copy local applications or CVs. Applicant email is optional. SMTP works on paid Render plans; Render Free blocks SMTP ports, so configure `RESEND_API_KEY` and `RESEND_FROM` in the service's Environment page to use the HTTPS API. Keep the API key private. The sender must belong to a domain verified with Resend.

## Deploy to Vercel with durable data

Vercel containers are stateless, so the Vercel deployment uses Supabase Postgres for jobs and applications and a **private** Supabase Storage bucket for CVs. The browser uploads each CV directly to Storage using a short-lived signed upload URL; CVs are never made public. Local Docker Compose continues to use SQLite and its named volume.

### 1. Create the Supabase resources

1. Create a Supabase project at [supabase.com/dashboard](https://supabase.com/dashboard).
2. In **Storage**, create a private bucket named `candidate-cvs`. Set the file size limit to 10 MB and allowed MIME type to `application/pdf`.
3. In **Project Settings → API**, copy the project URL and the `service_role` key. The service role key is secret; do not put it in the browser or commit it.
4. In **Project Settings → Database**, copy the Transaction pooler connection string for Vercel and ensure its SSL mode is `require`. Replace the password placeholder with your database password.

The app creates its tables and three sample jobs the first time it connects to an empty database. It does not import your local SQLite data or existing CVs.

### 2. Deploy from GitHub

1. Push the latest code to GitHub.
2. In Vercel, choose **Add New → Project**, import `hesbonangwenyi606/brightcore-recruitment-app`, and deploy the `main` branch. Vercel detects `Dockerfile.vercel` and builds the Python HTTP server as a container.
3. Before or after the first build, open **Project Settings → Environment Variables** and add these values for Production (and Preview if you want preview deployments):

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | Supabase Postgres connection string |
   | `SUPABASE_URL` | Supabase project URL |
   | `SUPABASE_SERVICE_ROLE_KEY` | Supabase `service_role` key; keep secret |
   | `SUPABASE_CV_BUCKET` | `candidate-cvs` |
   | `SESSION_SECRET` | A new random secret with at least 32 characters |
   | `ADMIN_PASSWORD` | A strong, unique initial admin password |
   | `SECURE_COOKIES` | `true` |
   | `PORT` | `80` |

   Add the optional `SMTP_*` values from the table above if you want applicant status emails. Never paste database, service role, SMTP, or session secrets into GitHub or chat.

   To generate a session secret locally in Windows PowerShell, run:

   ```powershell
   $bytes = New-Object byte[] 32
   [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
   [Convert]::ToBase64String($bytes)
   ```

   Copy the generated value directly into Vercel's `SESSION_SECRET` field.

4. Save the variables and choose **Redeploy** so the container starts with them. Open the Vercel URL and choose **Team login**. The username is `admin`; use the `ADMIN_PASSWORD` value you set.

The first server startup creates the admin and sample jobs. The admin password is only used on initial database setup; changing the Vercel variable later does not change an already-created admin account. Vercel and Supabase may charge depending on plan and usage; check their current pricing before choosing paid features.

### Vercel storage and security notes

- Keep the Storage bucket private. Admin CV links are signed and expire after two minutes.
- `SUPABASE_SERVICE_ROLE_KEY` grants broad project access. It is used only by the server and must remain a Vercel secret.
- Use the Supabase Transaction pooler connection string, not a local database or file path. Set `SESSION_SECRET` to a fresh random value; changing it signs out active admin sessions.
- Local applications, admin credentials, and uploaded CVs are not copied into the hosted Supabase project.

## Technology choices

- **Python standard library HTTP server:** keeps the application dependency-free and straightforward to run.
- **SQLite locally and PostgreSQL on Vercel:** SQLite keeps local setup simple; managed PostgreSQL provides durable hosted records and supports concurrent Vercel instances.
- **HTML, CSS, and JavaScript:** provide the public site and admin dashboard without a frontend build step.
- **Docker Compose locally and Vercel containers for hosting:** keep the local one-command workflow and package the existing Python server for Vercel.
- **Basic security controls:** salted PBKDF2-HMAC-SHA256 password hashes, HTTP-only and SameSite session cookies, authenticated admin routes, and PDF type/size checks. CV files are stored privately and served through an authenticated route.

## Assumptions and limitations

- This is a local demonstration/take-home app with one seeded admin account, no public admin registration, and no password reset flow.
- Sample jobs are inserted only when the database contains no jobs. Once the database has data, seed changes will not overwrite it.
- Duplicate applications are prevented for the same normalized email address and job. Cover notes are optional.
- Closing a job prevents new applications while retaining the existing role and applications.
- Applicants are notified only for Accepted or Rejected status decisions. SMTP is optional; without it, the status still saves.
- Local SQLite and file storage are intended for development. Hosted deployments use Supabase for durable records and private CV files, plus signed stateless admin cookies. Production still needs operational monitoring, backups, and a documented data-retention policy.

## Tests and continuous integration

Run the standard-library integration tests with:

```sh
python -m unittest discover -s tests -v
```

The tests cover password hashing, admin route protection, sample roles, the public search control, closed-job filtering, and duplicate application rejection. GitHub Actions runs the tests, validates the Compose configuration, and builds the Docker image for pushes and pull requests targeting `main`.

## Improvements with more time

I would add CSRF protection, configurable admin accounts and password rotation, pagination for larger applicant lists, more comprehensive audit logging, production deployment settings, and managed storage for uploaded files.
