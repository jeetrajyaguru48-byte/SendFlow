# Vercel + Neon + cron-job.org Deployment

This repo is now set up for a no-card deployment path using:

- Vercel Hobby for the React frontend
- Vercel Hobby for the FastAPI backend
- Neon free Postgres for the database
- cron-job.org for the scheduler

## Repo Layout

- Backend Vercel config: [vercel.json](/Users/j3et/Downloads/CODE/Email%20Automation/vercel.json:1)
- Backend entrypoint: [api/index.py](/Users/j3et/Downloads/CODE/Email%20Automation/api/index.py:1)
- Frontend Vercel config: [sendflow-pro-main/vercel.json](/Users/j3et/Downloads/CODE/Email%20Automation/sendflow-pro-main/vercel.json:1)
- Frontend API base: [sendflow-pro-main/src/api/client.ts](/Users/j3et/Downloads/CODE/Email%20Automation/sendflow-pro-main/src/api/client.ts:1)
- Scheduler endpoint: [backend/app/routers/internal.py](/Users/j3et/Downloads/CODE/Email%20Automation/backend/app/routers/internal.py:1)

## Before You Start

- Do not use SQLite in production on Vercel.
- Use Neon and paste the connection string into `DATABASE_URL`.
- Use two separate Vercel projects from the same GitHub repo:
  - one project rooted at the repo root for the backend
  - one project rooted at `sendflow-pro-main` for the frontend

## 1. Create A Neon Database

1. Sign up at `https://neon.com`.
2. Create a new project.
3. Copy the connection string from the dashboard.
4. Make sure it looks like this:

```text
postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
```

5. Keep that value ready for `DATABASE_URL`.

## 2. Prepare Google OAuth

Open your Google Cloud OAuth client and keep these values ready:

- `client_id`
- `client_secret`

You do not need to upload the JSON file into Vercel. Copy the values out of it.

## 3. Deploy The Backend To Vercel

1. Push this repo to GitHub.
2. In Vercel, click `Add New...` then `Project`.
3. Import this GitHub repo.
4. For the backend project:
- Keep the root directory as the repo root
- Framework preset can stay auto-detected or `Other`
5. Add these environment variables in Vercel before deploying:

```text
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=https://your-backend-project.vercel.app/auth/callback
SECRET_KEY=generate_a_long_random_secret
SCHEDULER_SECRET=generate_another_long_random_secret
DATABASE_URL=your_neon_connection_string
FRONTEND_URL=https://your-frontend-project.vercel.app
CORS_ORIGINS=https://your-frontend-project.vercel.app
BASE_URL=https://your-backend-project.vercel.app
```

6. Deploy the project.
7. Open:

```text
https://your-backend-project.vercel.app/health
https://your-backend-project.vercel.app/docs
```

Both should load successfully.

## 4. Deploy The Frontend To Vercel

1. In Vercel, click `Add New...` then `Project` again.
2. Import the same GitHub repo a second time.
3. For this frontend project:
- Set the Root Directory to `sendflow-pro-main`
- Framework preset should be `Vite`
4. Add this environment variable:

```text
VITE_API_URL=https://your-backend-project.vercel.app
```

5. Deploy the project.
6. Open the frontend URL and confirm it loads.

## 5. Finish Google OAuth Setup

In Google Cloud Console, add this Authorized redirect URI:

```text
https://your-backend-project.vercel.app/auth/callback
```

If your OAuth consent screen is still in testing mode, add your Gmail account as a test user.

## 6. Configure cron-job.org

1. Sign in to `https://cron-job.org`.
2. Create a new cronjob.
3. Set:
- URL: `https://your-backend-project.vercel.app/internal/scheduler/run`
- Request method: `POST`
- Execution schedule: every `5` minutes
4. Add this request header:

```text
X-Scheduler-Secret: your_scheduler_secret
```

5. Leave the request body empty.
6. Save the job.
7. Run a manual test once from cron-job.org.

## 7. Verify The Scheduler Endpoint

You can also test it yourself with curl:

```bash
curl -X POST "https://your-backend-project.vercel.app/internal/scheduler/run" \
  -H "X-Scheduler-Secret: your_scheduler_secret"
```

You want a JSON response with `ok: true`.

## 8. Use The App

1. Open the frontend.
2. Log in with Google.
3. Create a campaign.
4. Upload leads.
5. Click `Send`.
6. The campaign should stay scheduled.
7. cron-job.org will trigger the backend every 5 minutes.

## 9. Important Notes

- Vercel Hobby backend functions are free, but not meant for heavy long-running jobs.
- This scheduler path is fine for small personal usage.
- Do not keep the GitHub Actions scheduler enabled at the same time, or you may trigger sends twice.
- The older root-level frontend-only `vercel.json` has been replaced with a backend config, so the frontend must now be deployed from `sendflow-pro-main`.

## 10. Recommended Secrets

Generate secrets locally with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```
