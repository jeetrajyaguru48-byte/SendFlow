# SendFlow

SendFlow is a Gmail outreach app with:

- Google login
- multi-account sending
- campaign wizard
- lead import and mapping
- inbox and reply tracking
- analytics
- scheduled campaign processing via external cron

## Local Run

```bash
./run.sh
```

App URLs:

- Frontend: `http://localhost:8081`
- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

## Environment

Start from [.env.example](/Users/j3et/Downloads/CODE/Email%20Automation/.env.example:1).

Important variables:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `SECRET_KEY`
- `SCHEDULER_SECRET`
- `DATABASE_URL`
- `FRONTEND_URL`
- `CORS_ORIGINS`
- `BASE_URL`

## Production Deployment

Recommended:

- Frontend on Vercel
- Backend on Vercel
- Postgres on Neon
- cron-job.org for scheduled sending

Deployment guide:

- [DEPLOYMENT.md](/Users/j3et/Downloads/CODE/Email%20Automation/DEPLOYMENT.md:1)
- [VERCEL_NEON_DEPLOYMENT.md](/Users/j3et/Downloads/CODE/Email%20Automation/VERCEL_NEON_DEPLOYMENT.md:1)

## Production Files Added

- [render.yaml](/Users/j3et/Downloads/CODE/Email%20Automation/render.yaml:1)
- [vercel.json](/Users/j3et/Downloads/CODE/Email%20Automation/vercel.json:1)
- [sendflow-pro-main/vercel.json](/Users/j3et/Downloads/CODE/Email%20Automation/sendflow-pro-main/vercel.json:1)

## Notes

- Dev can use SQLite
- Production should use Postgres
- Production can use external cron like cron-job.org instead of a dedicated background worker
- Vercel deployment uses two projects: repo root for backend, `sendflow-pro-main` for frontend
