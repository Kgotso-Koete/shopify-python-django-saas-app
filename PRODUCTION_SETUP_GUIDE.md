# Production Deployment Guide: Complete Setup Options

This guide outlines three paths to deploy your SaaS application to production. You can choose the path that best fits your budget, technical expertise, and friction tolerance.

We will compare the three main deployment options and provide a deep dive into setting up the **100% Free** stack.

---

## The 3 Deployment Options

| Feature              | Option A: AWS (Paid, Low Friction)       | Option B: Render (Paid, Medium Friction) | Option C: 100% Free Stack (High Friction)         |
| :------------------- | :--------------------------------------- | :--------------------------------------- | :------------------------------------------------ |
| **Cost**             | ~$60 - $150+/month                       | ~$38/month                               | $0/month                                          |
| **Friction**         | Low (if using AWS Elastic Beanstalk/ECS) | Low/Medium (Render Blueprint)            | High (Multiple separate services)                 |
| **Frontend**         | AWS CloudFront + S3                      | Render Static Site                       | Render Static Site or Vercel                      |
| **Backend API**      | AWS EC2 / ECS / AppRunner                | Render Web Service (Starter)             | Render Web Service (Free Tier)                    |
| **Database**         | AWS RDS (PostgreSQL)                     | Render Managed PostgreSQL                | Neon.tech (Serverless Postgres)                   |
| **Redis**            | AWS ElastiCache                          | Render Managed Redis                     | Upstash (Serverless Redis)                        |
| **Background Tasks** | AWS ECS Workers                          | Render Worker Service                    | _Requires custom container setup or Oracle Cloud_ |
| **Storage**          | AWS S3                                   | Cloudflare R2                            | Cloudflare R2                                     |
| **Emails**           | AWS SES                                  | SendGrid / Brevo                         | Brevo / SMTP2GO                                   |

### Option A: AWS (Recommended for Enterprise / Scaling)

**Best for:** Businesses with a budget who want everything under one roof (AWS) and need unlimited scaling capabilities.

- **How it works:** You deploy using AWS ECS or Elastic Beanstalk. You use managed RDS for Postgres, ElastiCache for Redis, and S3 for media storage.
- **Cost:** While AWS has a free tier for the first 12 months (e.g., t3.micro EC2, small RDS), a production-ready setup with load balancers and NAT gateways will quickly cost $60-$150+/mo.
- **Setup:** Use the `docker-compose.prod.yml` as a reference for your ECS task definitions, or use AWS AppRunner.

### Option B: Render.com (Recommended for Startups)

**Best for:** Fast-moving startups who want an easy "push-to-deploy" experience without the complexity of AWS, at a predictable price.

- **How it works:** The repository includes a `render.yaml` Blueprint. Render automatically spins up your Postgres, Redis, API, Celery Workers, and Frontend.
- **Cost:** ~$38/month for the backend, workers, DB, and Redis (Starter plans). The frontend static site is free.
- **Setup:** Connect your GitHub to Render, select "New Blueprint", and it deploys automatically.

### Option C: The 100% Free Stack

**Best for:** Hobby projects, MVPs, and developers who want to validate their idea with zero running costs.

- **How it works:** We piece together generous free tiers from various specialized SaaS providers.
- **Trade-offs:**
  - **Cold Starts:** Render's free Web Service spins down after 15 minutes of inactivity. The first request after this will take 30-50 seconds to respond. (Can be mitigated with uptime monitoring tools).
  - **Celery Workers:** Render does not provide free background workers. You either run tasks synchronously, or you must use a free VPS (like Oracle Cloud Always Free) to run the full `docker-compose.prod.yml`.
  - **Storage Limits:** Neon DB is limited to 0.5GB. Upstash is limited to 10k commands/day.

---

## Implementing Option C: The 100% Free Stack

If you want to run this codebase without spending a dime, follow these steps exactly. We will use a distributed free-tier architecture.

### Pre-Deployment: Generate Your Secrets

Before creating any accounts, generate two secret keys that you'll reuse across multiple services. Run these commands in your terminal:

```bash
# 1. Generate DJANGO_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(50)[:50])"

# 2. Generate HASHID_FIELD_SALT
python3 -c "import secrets; print(secrets.token_urlsafe(50)[:50])"
```

> **⚠️ CAUTION:** Save these securely in your [`packages/backend/.env`](./packages/backend/.env) file. If you lose them, existing user sessions and URL hashes will break.

---

### Step 1: Database - Neon.tech (Free PostgreSQL)

Neon provides a generous serverless Postgres database.

1. Go to [Neon.tech](https://neon.tech/) and sign up.
2. Create a new project (e.g., `saas-db`).
3. On the dashboard, find your **Connection String**. It looks like:
   `postgresql://[user]:[password]@[host]/[dbname]?sslmode=require`
4. Save this as your `DATABASE_URL` in your [`packages/backend/.env`](./packages/backend/.env) file (you will need it for the Render Dashboard in Step 5).

---

### Step 2: Cache & Queue - Upstash (Free Redis)

Upstash provides serverless Redis.

1. Go to [Upstash.com](https://upstash.com/) and sign up.
2. Create a new Redis Database.
3. Scroll down to the **Connect to your database** section.
4. Copy the **Redis URL** (starts with `rediss://...`).
5. Save this as your `REDIS_CONNECTION` in your [`packages/backend/.env`](./packages/backend/.env) file (you will need it for the Render Dashboard in Step 5).

---

### Step 3: Storage - Cloudflare R2 (Free S3-Compatible Storage)

Cloudflare R2 gives you 10GB of free storage with zero egress fees.

1. Sign up at [Cloudflare](https://dash.cloudflare.com).
2. Go to **R2 Object Storage** and create a bucket (e.g., `saas-media`).
3. Click **Manage R2 API Tokens** and create a token with **Object Read & Write** permissions.
4. You will need to save the following in your [`packages/backend/.env`](./packages/backend/.env) file (you will need them for the Render Dashboard in Step 5):
   - `R2_ACCESS_KEY_ID`: Your Access Key ID
   - `R2_SECRET_ACCESS_KEY`: Your Secret Access Key
   - `R2_BUCKET_NAME`: The name of the bucket you created (`saas-media`)
   - `R2_ENDPOINT_URL`: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` (replace `<ACCOUNT_ID>` with your Account ID from the dashboard)
   - `STORAGE_BACKEND`: `r2`

---

### Step 4: Emails - Brevo or SMTP2GO (Free SMTP)

We need a free service to send transactional emails (password resets, etc.).

1. Sign up for [Brevo](https://www.brevo.com/) (300 emails/day free) or [SMTP2GO](https://www.smtp2go.com/) (1,000 emails/month free). No credit card required.
2. Verify your sender domain or email address.
3. Go to SMTP Settings and generate an API/SMTP password.
4. You will need: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD`. Save these in your [`packages/backend/.env`](./packages/backend/.env) file.

---

### Step 5: Backend - Render Free Tier

We will host the Django API on Render's free tier.

1. Go to [Render.com](https://render.com) and sign in.
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repo.
4. **Configuration:**
   - **Name:** `saas-backend`
   - **Runtime:** Docker
   - **Dockerfile Path:** `./packages/backend/Dockerfile.render`
   - **Plan:** Free
5. **Environment Variables:**

| Variable                             | Value                                                                | Notes                           |
| ------------------------------------ | -------------------------------------------------------------------- | ------------------------------- |
| `DJANGO_SECRET_KEY`                  | _(from Pre-Deployment)_                                              |                                 |
| `HASHID_FIELD_SALT`                  | _(from Pre-Deployment)_                                              |                                 |
| `DATABASE_URL`                       | _(from Step 1: Neon)_                                                | MUST include `?sslmode=require` |
| `REDIS_CONNECTION`                   | _(from Step 2: Upstash)_                                             |                                 |
| `STORAGE_BACKEND`                    | `r2`                                                                 |                                 |
| `R2_ENDPOINT_URL`                    | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`                      |                                 |
| `R2_ACCESS_KEY_ID`                   | _(from Step 3)_                                                      |                                 |
| `R2_SECRET_ACCESS_KEY`               | _(from Step 3)_                                                      |                                 |
| `R2_BUCKET_NAME`                     | _(from Step 3)_                                                      |                                 |
| `EMAIL_BACKEND`                      | `django.core.mail.backends.smtp.EmailBackend`                        |                                 |
| `EMAIL_HOST`                         | _(from Step 4)_                                                      | e.g. `smtp-relay.brevo.com`     |
| `EMAIL_PORT`                         | `587`                                                                |                                 |
| `EMAIL_HOST_USER`                    | _(from Step 4)_                                                      |                                 |
| `EMAIL_HOST_PASSWORD`                | _(from Step 4)_                                                      |                                 |
| `EMAIL_USE_TLS`                      | `True`                                                               |                                 |
| `EMAIL_FROM_ADDRESS`                 | _(Verified email from Step 4)_                                       |                                 |
| `DJANGO_ALLOWED_HOSTS`               | `saas-backend.onrender.com`                                          | No `https://`                   |
| `WEB_APP_URL`                        | `https://saas-frontend.vercel.app`                                   | Your frontend URL               |
| `API_URL`                            | `https://saas-backend.onrender.com`                                  | Your backend URL                |
| `CORS_ALLOWED_ORIGINS`               | `https://saas-frontend.vercel.app`                                   | We will set this up next        |
| `CSRF_TRUSTED_ORIGINS`               | `https://saas-frontend.vercel.app,https://saas-backend.onrender.com` |                                 |
| `SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS` | `saas-frontend.vercel.app`                                           | No `https://`                   |
| `ENVIRONMENT_NAME`                   | `production`                                                         |                                 |
| `DJANGO_DEBUG`                       | `False`                                                              |                                 |
| `AWS_XRAY_SDK_ENABLED`               | `False`                                                              | Disables AWS tracing            |
| `CELERY_TASK_ALWAYS_EAGER`           | `True`                                                               | Runs tasks synchronously        |

**Handling Background Tasks (Celery) on Free Tier:**
Since Render doesn't offer free worker services, background tasks will fail to process if you don't have a worker.
**Option 1:** Avoid using background tasks for essential features, or set `CELERY_TASK_ALWAYS_EAGER = True` in your settings to execute tasks synchronously during the HTTP request.
**Option 2:** Use a free VPS like **Oracle Cloud Always Free** to deploy the entire stack using `docker-compose.prod.yml` instead of Render.

> **💡 Pro Tip:** To prevent your Render Free Web Service from going to sleep, sign up for a free uptime monitoring service like [cron-job.org](https://cron-job.org/) and set it to ping your backend URL `https://saas-backend.onrender.com/api/health/` every 10 minutes.

**Run database migrations:**

```bash
docker-compose -f docker-compose.yml run --no-deps --rm backend bash -c "DATABASE_URL='postgresql://<your-database-url>' DJANGO_SECRET_KEY='dummy-key-for-migrations' HASHID_FIELD_SALT='dummy-salt' REDIS_CONNECTION='redis://localhost:6379' DJANGO_DEBUG='False' ./scripts/runtime/run_migrations.sh"
```

---

### Step 6: Frontend - Vercel or Render Static Sites (Free)

Host your React web app.

**Option 1: Vercel (Fastest Setup)**

1. Go to [Vercel](https://vercel.com) and connect your repo.
2. In the Vercel project configuration page, set the following:
   - **Root Directory:** `packages/webapp`
   - **Framework Preset:** Select **Vite** from the dropdown.
   - **Build Command:** `pnpm nx build webapp` _(Vercel runs this on their servers, do NOT run it locally)_
   - **Output Directory:** `build` _(this project uses `build` instead of Vite's default `dist`)_
3. Under **Environment Variables**, add:
   - `VITE_BASE_API_URL`: Your Render backend URL with `/api` appended. For example, if Render gave you `https://saas-backend.onrender.com`, set this to `https://saas-backend.onrender.com/api`.
   - `VITE_ENVIRONMENT_NAME`: `production`
4. Click **Deploy**!

**Option 2: Render Static Site**

1. In Render, create a new **Static Site**.
2. **Build Command:** `npm install -g pnpm@10 && pnpm install --frozen-lockfile && pnpm nx build webapp`
3. **Publish Directory:** `packages/webapp/build`
4. Set the same Environment Variables as above.

---

### Step 7: Finalizing Connections

Once your frontend is deployed (e.g., `https://saas-frontend.vercel.app`), go back to your Render Backend settings and update these variables:

- `WEB_APP_URL` = `https://saas-frontend.vercel.app`
- `API_URL` = `https://saas-backend.onrender.com`
- `VITE_WEB_APP_URL` = `https://saas-frontend.vercel.app`
- `VITE_EMAIL_ASSETS_URL` = `https://saas-frontend.vercel.app/email-assets`

Restart your Render backend service. You now have a fully functioning, 100% free production stack!

---

### Step 8: Background Tasks — Making Celery Work on the Free Tier

The codebase supports two task backends (`TASK_BACKEND` setting): `lambda` (default, requires AWS EventBridge) and `celery` (built for exactly this scenario — see `packages/backend/common/task_backends/__init__.py`). On Render's free tier there is no persistent worker process available, so background tasks currently fail silently: the `lambda` backend tries to call AWS and errors/no-ops outside AWS.

**8.1 — Fix on-demand tasks (zero cost, no new service needed)**

Add these two environment variables to your existing `saas-backend` Render web service (the same one from Step 5):

| Variable                   | Value    |
| -------------------------- | -------- |
| `TASK_BACKEND`             | `celery` |
| `CELERY_TASK_ALWAYS_EAGER` | `True`   |

With `CELERY_TASK_ALWAYS_EAGER=True`, any task sent via `send_task()`/`.delay()` (e.g. a user requesting a data export) runs **synchronously, inline, in the same request** — no broker connection or worker process required. This is a pure config change; no code needs to change.

**8.2 — Understand what this does _not_ fix**

`CELERY_BEAT_SCHEDULE` entries — the hourly backup-schedule check, the daily backup cleanup, and (once Contentful is enabled in Step 11) the 5-minute Contentful sync — rely on **Celery Beat**, a scheduler that needs a continuously running process. There is no free way to run a continuous process on Render, so none of these will fire automatically on the free stack. On-demand actions (anything a user triggers directly) will work; anything meant to happen "every N minutes/hours" won't, until you add a real worker.

**8.3 — Your options if you need real scheduling later**

- **Stay free:** move the whole stack to an Oracle Cloud Always Free VPS (see the section at the bottom of this doc) and run `docker-compose.prod.yml` as-is — real Celery worker + Beat, no compromises.
- **Spend a little:** add just the `celery-beat` service (and `celery-worker` if you have real async work) from `render.yaml` on Render's Starter plan (~$7/mo each).
- **Stay manual:** trigger the periodic jobs yourself from Django admin or `python manage.py <command>` when needed, and skip auto-scheduling for now.

---

### Step 9: AI Integration — OpenAI (Optional)

OpenAI powers a few optional features in the boilerplate: the demo "generate SaaS ideas" form, AI-assisted translations, and the MCP-based AI agent/chat. None of these are required for the app to run — leave `OPENAI_API_KEY` unset and they simply stay disabled.

**Cost reality check:** the OpenAI API is pay-as-you-go, not free. Reports on whether new accounts still get an automatic trial credit conflict as of mid-2026 — some say a small ($5) credit still appears automatically, others say it's been discontinued and requires a manual top-up. Don't rely on getting one; budget for OpenAI's $5 minimum prepaid balance if you want to test this feature.

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and create a key.
2. Add a billing method (min. $5 prepaid) — the API rejects requests without one.
3. Add to your Render backend env vars:

   | Variable         | Value                                        |
   | ---------------- | -------------------------------------------- |
   | `OPENAI_API_KEY` | `sk-...`                                     |
   | `OPENAI_MODEL`   | e.g. `gpt-4o-mini` (cheapest capable option) |

---

### Step 10: Payments — Stripe (Test/Dev Mode)

Test mode is genuinely free — no live charges, no payout/country restrictions, since no real money moves. This is the right choice for validating the repo before you need real payouts.

1. In the [Stripe Dashboard](https://dashboard.stripe.com/apikeys), make sure the **Test mode** toggle (top right) is on, then go to Developers → API keys and copy the Secret key (`sk_test_...`).
2. Add to your Render backend env vars:

   | Variable                 | Value         |
   | ------------------------ | ------------- |
   | `STRIPE_TEST_SECRET_KEY` | `sk_test_...` |
   | `STRIPE_LIVE_MODE`       | `False`       |
   | `STRIPE_CHECKS_ENABLED`  | `True`        |

3. Create the Stripe products/prices. The repo already has a management command that reads your plan definitions (`free_plan`, `monthly_plan`, `yearly_plan` — see `packages/backend/apps/finances/constants.py`) and creates matching Stripe Products and Prices via the API. Run it once from the Render Shell tab:

   ```bash
   python manage.py init_subscriptions
   ```

4. Set up the webhook: Dashboard → Developers → Webhooks → Add endpoint.
   - **URL:** `https://<your-backend>.onrender.com/api/finances/stripe/webhook/` (this is dj-stripe's default path — confirmed from `apps/finances/urls.py`, which mounts `djstripe.urls` at `api/finances/stripe/`)
   - Select **all events** ("Select all") — this is a test-mode sandbox, so there's no cost or risk to over-selecting, and it saves you from guessing which categories the app's handlers in `apps/finances/webhooks.py` actually need (currently a mix of Subscription Schedule, Invoice, Payment Method, and Charge/Refund events).
   - If you're on Stripe's newer wizard (Select events → Choose destination type → Configure), pick **Webhook endpoint** as the destination type on the next step, then enter the URL.
   - If asked to choose a payload format, pick **Snapshot** (the classic full-payload format), not **Thin payload**. dj-stripe 2.8.1 (the version this app pins) reads event fields directly off the payload it receives — it has no code to fetch an object separately, which is what thin events would require. Thin payload will silently break webhook processing.
   - Copy the **Signing secret** (`whsec_...`) and add it as `DJSTRIPE_WEBHOOK_SECRET` on the backend.

5. Frontend: add `VITE_STRIPE_PUBLISHABLE_KEY=pk_test_...` to your Vercel/Render Static Site env vars. This one is a publishable key — safe to expose in the browser bundle.

---

### Step 11: CMS — Contentful (Free Tier, incl. Privacy Policy & Terms)

Contentful's free (Community) plan covers this easily — one space, generous API limits. The privacy policy and terms & conditions pages are already wired up in the webapp; they just need the content type and content created in Contentful.

**11.1 — Create a space and get your tokens**

You'll need two different token types — mixing them up is the most common mistake:

- **Content Delivery token** (read-only, safe to expose publicly, used by the live webapp): in your space, go to Settings → API keys → Add API key (or use the default one Contentful creates) → copy the **Space ID** and the **"Content Delivery API - access token"**. Use Delivery, not Preview — the app only ever queries published content and has no preview-mode code path at all.
- **Content Management token** (write access, used once, locally, for the migration script): this has moved in Contentful's UI — it's no longer nested under the per-space API keys page. Go to the account-level **Settings (gear icon, top right) → CMA tokens** → **Create personal access token** → name it → **Generate**. Copy it immediately (starts with `CFPAT-`) — it's shown once only. **Important:** this token is account-wide, not auto-scoped to your space — if the migration script later fails with an access error, come back here and check for an **Authorize** button next to your token for this specific space.

**11.2 — Create the content model**

The repo's migration script creates _both_ content types you need in one run — `appConfig` (with `privacyPolicy` and `termsAndConditions` fields) and `demoItem`:

```bash
cd packages/contentful
cp .env.shared .env
# edit .env with:
#   CONTENTFUL_SPACE_ID=<space id>
#   CONTENTFUL_ACCESS_TOKEN=<the MANAGEMENT token, starts with CFPAT- — not the delivery one>
#   CONTENTFUL_ENVIRONMENT=master
node scripts/run_migrations.js
```

This runs entirely on your own machine and only talks to Contentful's API — it doesn't touch Render, Docker Compose, or your Django backend at all, so nothing else needs to be running for it. A successful run ends with `Migration Done!`.

> **Troubleshooting — "The provided space does not exist or you do not have access":** Contentful reached your request and rejected it on auth grounds, not a script bug. Check, in order: (1) your CMA token is authorized for this specific space (see 11.1), (2) `CONTENTFUL_SPACE_ID` matches exactly what's in your space's URL — `app.contentful.com/spaces/<this part>/home`, (3) `CONTENTFUL_ACCESS_TOKEN` actually starts with `CFPAT-` and isn't a Delivery/Preview token, (4) you didn't leave a `<CHANGE_ME>`-style placeholder from `.env.shared` uncommented in `.env`.

**11.3 — Add the privacy policy and terms content**

In the Contentful web app: Content → Add entry → **App Config**, then fill in:

- **Name:** `Global App Config` (this exact value — it's a locked dropdown field)
- **Privacy policy:** your markdown text
- **Terms and Conditions:** your markdown text

Click **Publish** (top right) — not just Save. Unpublished entries never reach the Content Delivery API your frontend queries.

> **Troubleshooting — "Validation failed" on publish, with no specifics:** Contentful's toast message is generic; the actual reason is shown as a small red note directly under the specific failing field once you look at the entry. Most likely culprits: the Name field isn't exactly `Global App Config` (typos, casing, trailing spaces), or one of the three required fields (name / privacyPolicy / termsAndConditions) is still empty.

**11.4 — Wire up the frontend**

The webapp's Apollo Client queries Contentful's GraphQL Content Delivery API (`graphql.contentful.com`) **directly from the browser** — it doesn't go through the Django backend at all (confirmed in `packages/webapp-libs/webapp-api-client/src/graphql/apolloClient.ts`). So only the frontend needs these:

| Variable                | Value                      |
| ----------------------- | -------------------------- |
| `VITE_CONTENTFUL_SPACE` | `<space id>`               |
| `VITE_CONTENTFUL_TOKEN` | `<content DELIVERY token>` |
| `VITE_CONTENTFUL_ENV`   | `master`                   |

Add these to your Vercel/Render Static Site env vars, then **trigger a genuinely new deploy** — not just a restart.

> **Troubleshooting — page shows "Received status code 400" and the failed request URL contains `environments/undefined`:** this means `VITE_CONTENTFUL_ENV` never reached the built JS bundle. Vite bakes every `VITE_*` variable into the bundle at **build time**, not runtime — adding the variable in your host's dashboard does nothing to an already-built deployment. You need a fresh build (disable build cache if your platform offers that toggle) after adding or changing any `VITE_*` variable, then a hard-refresh/private window to rule out browser caching.

`/privacy-policy` and `/terms-and-conditions` will now render your Contentful content instead of the "not configured" placeholder.

**11.5 — Demo Item content (optional — skip unless you specifically want to see it)**

There's a second content type from the same migration, `demoItem`, powering an optional `/demo-items` showcase page. It has zero bearing on the actual app and is safe to skip entirely.

If you do want it working: there's a **confirmed bug in the boilerplate itself** (verified identical against the upstream `apptension/saas-boilerplate` repo, not something introduced by this fork). The migration creates the `image` field as plain text (`Symbol`), but the frontend's GraphQL query expects a Media/Asset reference (`image { title url }`). Creating an entry with a plain image URL fails at publish-time query with:

```json
{
  "errors": [
    {
      "message": "Field \"image\" must not have a selection since type \"String\" has no subfields."
    }
  ]
}
```

Fix, if you want it: **Content model → Demo Item** → delete the **Image** field → re-add it as **Media → One file**, keeping the field ID exactly `image` → save the content type → go back to your entry, upload an actual image file (not a URL string) → publish. Note that even after this fix, the uploaded image may not render correctly in the demo UI itself — this is throwaway showcase code, not something worth spending more time on beyond confirming the GraphQL error is resolved.

> **Note:** the backend's `synchronize_contentful_content` Celery Beat task (every 5 minutes) mirrors Contentful's `demoItem` data server-side for the CRUD demo — it is unrelated to the privacy policy/terms pages above, and per Step 8, won't run on the free stack anyway. This is expected and doesn't block anything you're setting up here.

---

### Step 12: Other Deployment Items Worth Knowing About

A few remaining pieces from the codebase that don't need action now, but are worth flagging:

- **Sentry (error tracking, optional):** `SENTRY_DSN` — Sentry's free Developer plan (5k errors/month) works fine here. Leave unset to skip.
- **WebSockets/real-time notifications:** the in-app notification center uses a `WEB_SOCKET_API_ENDPOINT_URL` designed for AWS API Gateway. On Render this isn't wired up in `render.yaml` at all — real-time notifications likely won't work on the free stack without extra work. Not required for anything else to function.
- **Flower (Celery monitoring):** only relevant once you have a real worker running (see Step 8.3) — skip for now.

---

## Alternative Free Option: Oracle Cloud Always Free VPS

If you need Celery Background Workers and a complete replica of a paid deployment, the only truly free option is an **Oracle Cloud ARM VPS** (4 vCPUs, 24GB RAM).

1. Sign up for Oracle Cloud (requires a credit card for verification, but won't be charged).
2. Provision an Always Free Ampere A1 Compute instance (Ubuntu).
3. Install Docker and Docker Compose.
4. Clone your repository to the VPS.
5. Copy [`.env.vps.example`](./.env.vps.example) to `.env.prod` and fill it out (using free Neon/Upstash or running them locally on the VPS).
6. Run `docker compose -f docker-compose.prod.yml up -d`.
   _(Note: Oracle Cloud registrations are known to be difficult due to strict anti-fraud card checks, but it remains the most powerful free server available)._
