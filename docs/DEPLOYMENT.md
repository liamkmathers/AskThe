# Deployment plan

*2026-10-30. A plan, nothing deployed yet. Platform facts checked on vendor docs that day (sources at the end); a few marked unverified.*

## Recommendation: Railway, about $5 a month

| | Railway | Fly.io | Render | Vercel | Small VPS |
| --- | --- | --- | --- | --- | --- |
| Persistent disk | Volume ($0.15/GB) | Volume, daily snapshots | Paid plans; brief downtime per deploy | None: needs a hosted database first | Local disk |
| 14 s streamed answers | Up to 15 min a request | Yes | Yes (assumed) | 300 s (Hobby), 800 s (Pro) | Yes |
| Deploy on push to `main` | Built in | GitHub Action | Built in | Built in | Scripted |
| Private access | App password | App password | App password | Paid add-on (unverified) or app password | App password |
| Cost a month | ~$5 | ~$4 | ~$7.25 | $0–20+, plus a database | ~€4–5 (unverified) |
| Effort | Lowest | Low–medium | Low | High (store adapter first) | Highest |

Railway: deploys from GitHub `main` on every push, has volumes for SQLite, and handles long streams. Fly.io is the runner-up if automatic volume snapshots matter more than setup. Vercel streams fine now, but has no disk, so saved answers would need a hosted database first: reasonable later (Phase C), not first. Model costs are separate: about $0.055 an answer.

## Phase A: private demo

**In the repo:**
1. **Database path from the environment** (`ASKTHE_DB_PATH`), so the volume mounts at `/data` without hiding the committed raw files and profiles.
2. **Dockerfile** (`python:3.12-slim`, `uv sync --frozen --no-dev`, the app, creators, config, raw files and profiles; `.dockerignore` for the database and `.env`).
3. **Start-up:** `segment` then `index` (both incremental: only changed videos), then `serve` on `0.0.0.0:$PORT`, for every creator.
4. **`/healthz`** (no password), returning video and profile counts; used as the platform's health check so a broken build never replaces a working one.
5. **Password gate:** one password (`ASKTHE_ACCESS_PASSWORD`), a small form setting a signed cookie (`ASKTHE_SESSION_SECRET`); everything but `/healthz` gated; off when unset (local).
6. **Rate limit** on asking: per IP, e.g. 10 an hour and 30 a day; a friendly 429 on the page.
7. **Daily spend cap:** each answer's cost (from `[prices]`) added to a `spend` table; above `ASKTHE_DAILY_BUDGET_USD` (start at $3, about 55 answers) answering pauses until tomorrow. Plus a monthly limit in the Anthropic console.
8. **Logging:** one line per question (answer ID, coverage, seconds, cost, hashed IP); never secrets.

**In Railway:** create a project from the GitHub repo (`main`), add a volume at `/data`, set the variables (`ASKTHE_ANTHROPIC_API_KEY`, `ASKTHE_OPENAI_API_KEY`, `ASKTHE_ACCESS_PASSWORD`, `ASKTHE_SESSION_SECRET`, `ASKTHE_DB_PATH=/data/askthe.db`, `ASKTHE_DAILY_BUDGET_USD`), set the health check to `/healthz`, generate a domain.

**Check:** without the password you get the form, `/healthz` is 200; an answer streams; after a redeploy, an old `/a/<id>` link still works (the volume holds); 11 quick questions get a 429; a $0.01 budget gets the pause message.

## Phase B: shared with the creator

His own password or link (so his use shows separately); a custom domain; a private `/admin` page (recent questions, flags, daily spend); nightly backups; CI (`pytest`, `ruff`) before each deploy.

## Phase C: public, only with his agreement

No accounts at first (history stays in the browser). Bot protection and tighter per-IP limits; daily and monthly caps with alerts; reuse answers to repeated questions. Stay on SQLite until one instance isn't enough, then a Postgres store adapter (search via full-text, vectors via pgvector), wired in `askthe/wiring.py`.

## Data in production

1. **New videos:** fetched on the Mac, profiled (about $0.14 each, locally or by an agent, not in CI), raw files and profiles pushed to `main`. Unprofiled videos are left out of answers (D22), so pushing early is safe.
2. **On deploy:** start-up restores profiles and embeds only new videos (fractions of a cent).
3. **Saved answers and flags** are the only data that can't be rebuilt. Move them to their own database file on the volume, and back it up nightly (a copy uploaded to cheap object storage).

## Risks

- **A leaked link or password** spends money: the daily cap and the console limit bound it. Build the cap before the first deploy.
- **SQLite** is fine for one instance at this scale; move to Postgres for several instances or if "database is locked" appears.
- **YouTube's terms** on showing transcript quotes publicly and on fetching transcripts outside its API: get a view before Phase C. Another reason the creator's agreement comes first.
- **Secrets** live only in the platform's variables; use separate, limited keys for production.

## Open questions

1. Railway (simplest) or Fly.io (built-in snapshots)?
2. One shared password, or a personal link per person?
3. What daily and monthly spend limit for the demo?
4. Move saved answers to their own database file now?
5. Host one creator now, or after the catalog change lands?

**Sources:** [Vercel function limits](https://vercel.com/docs/functions/limitations), [Fly.io pricing](https://docs.fly.io/about/pricing), [Fly.io auto-stop](https://docs.fly.io/launch/autostop-autostart/), [Railway plans](https://docs.railway.com/reference/pricing/plans), [Railway networking limits](https://docs.railway.com/networking/public-networking/specs-and-limits), [Railway volumes](https://docs.railway.com/volumes), [Render disks](https://render.com/docs/disks).
