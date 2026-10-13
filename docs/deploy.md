# Deploy for free

The whole app runs as **one free web service on Render** (the API also serves the web app), with the database on **Neon's free Postgres**, which includes pgvector and doesn't expire. Hosting costs nothing; you pay only for OpenAI usage.

```
Browser ──▶ Render (free web service: FastAPI + built React app) ──▶ Neon (free Postgres + pgvector)
                                   └──────────────▶ OpenAI API
```

**What to expect from free tiers:** the Render service sleeps after 15 minutes without visitors, and the first visit afterwards takes about a minute while it wakes up. Neon also pauses an idle database and wakes it in well under a second. Before sharing the link or a demo, open it once to wake it.

## 1. Protect your OpenAI budget

The demo accounts are public, so anyone with the link can chat and spend your credits.

1. In the OpenAI dashboard, open **Settings → Limits** and set a monthly budget (for example $5).
2. Optionally create a separate API key just for this deployment, so you can revoke it independently.

The app also limits each account to 6 messages per minute (`SUPPORT_RATE_LIMIT_PER_MINUTE` in `render.yaml`). Every visitor shares the demo accounts, so in practice that's a site-wide cap.

## 2. Create the database on Neon

1. Sign up at **neon.com** (no credit card needed) and create a project. Pick the region closest to where you'll deploy on Render.
2. On the project dashboard, click **Connect**.
3. **Turn off "Connection pooling"**, so the host name doesn't contain `-pooler`. The app manages its own connection pools, and the pooled endpoint doesn't support the prepared statements the database driver uses.
4. Copy the connection string. It looks like:
   ```
   postgresql://neondb_owner:...@ep-cool-name-123456.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```
   Use it exactly as shown; the app converts it for each driver itself.

You don't need to create tables or enable pgvector. The app does both on first start.

## 3. Deploy on Render

1. Make sure the code is pushed to GitHub and the **Actions** tab shows CI passing. Render deploys only commits whose checks pass.
2. Sign in at **render.com** with GitHub.
3. Click **New → Blueprint**, select your `multi-agent-support-system` repository, and continue. Render reads `render.yaml`.
4. Fill in the two prompted values:
   - `SUPPORT_DATABASE_URL`: the Neon connection string from step 2.
   - `OPENAI_API_KEY`: your OpenAI key.

   `SUPPORT_JWT_SECRET` is generated for you as a long random value.
5. Click **Apply**. The first build takes roughly 5 to 10 minutes. On start, the logs show:
   ```
   Applying database migrations...
   Seeding demo data (skipped if present)...
   Indexing the help center (only changed articles)...
   Starting the server on port ...
   ```
6. Open the URL Render shows (`https://multi-agent-support-system-xxxx.onrender.com`) and sign in with a demo account.

If Render asks you to choose a paid instance type for the Docker service, create the service manually instead: **New → Web Service**, pick the repository, choose **Docker** as the runtime and **Free** as the instance type, set **Health check path** to `/healthz`, and add the same environment variables as in `render.yaml`.

## 4. After it's live

- Put the URL in your GitHub repo's **About → Website** field and at the top of the README.
- Every push to `main` redeploys automatically once CI passes.
- The first start embeds the help center with OpenAI (a fraction of a cent). Later starts skip it unless articles changed.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Deploy fails with `required variable ... is missing` or a settings error | An environment variable is empty. Check **Environment** in the Render dashboard. |
| Logs show `password authentication failed` or `could not translate host name` | The database URL is wrong. Copy it again from Neon's **Connect** dialog. |
| Errors mentioning `prepared statement` | You used the pooled URL (host contains `-pooler`). Turn off connection pooling in Neon and use the direct URL. |
| Chat replies "Something went wrong" | Usually OpenAI: an invalid key, budget reached, or a model your account can't use (`model_not_found` in the logs). Set `SUPPORT_LLM_MODEL` / `SUPPORT_TRIAGE_MODEL` to models you have access to. |
| Site takes about a minute to load | Normal on the free plan after 15 idle minutes. |
| Out-of-memory restarts | The free instance has 512 MB. Keep `SUPPORT_DB_POOL_SIZE` low (3 is set). |
