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

| Variable               | Value                                                                | Notes                           |
| ---------------------- | -------------------------------------------------------------------- | ------------------------------- |
| `DJANGO_SECRET_KEY`    | _(from Pre-Deployment)_                                              |                                 |
| `HASHID_FIELD_SALT`    | _(from Pre-Deployment)_                                              |                                 |
| `DATABASE_URL`         | _(from Step 1: Neon)_                                                | MUST include `?sslmode=require` |
| `REDIS_CONNECTION`     | _(from Step 2: Upstash)_                                             |                                 |
| `STORAGE_BACKEND`      | `r2`                                                                 |                                 |
| `R2_ENDPOINT_URL`      | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`                      |                                 |
| `R2_ACCESS_KEY_ID`     | _(from Step 3)_                                                      |                                 |
| `R2_SECRET_ACCESS_KEY` | _(from Step 3)_                                                      |                                 |
| `R2_BUCKET_NAME`       | _(from Step 3)_                                                      |                                 |
| `EMAIL_BACKEND`        | `django.core.mail.backends.smtp.EmailBackend`                        |                                 |
| `EMAIL_HOST`           | _(from Step 4)_                                                      | e.g. `smtp-relay.brevo.com`     |
| `EMAIL_PORT`           | `587`                                                                |                                 |
| `EMAIL_HOST_USER`      | _(from Step 4)_                                                      |                                 |
| `EMAIL_HOST_PASSWORD`  | _(from Step 4)_                                                      |                                 |
| `EMAIL_USE_TLS`        | `True`                                                               |                                 |
| `EMAIL_FROM_ADDRESS`   | _(Verified email from Step 4)_                                       |                                 |
| `DJANGO_ALLOWED_HOSTS` | `saas-backend.onrender.com`                                          | No `https://`                   |
| `CORS_ALLOWED_ORIGINS` | `https://saas-frontend.vercel.app`                                   | We will set this up next        |
| `CSRF_TRUSTED_ORIGINS` | `https://saas-frontend.vercel.app,https://saas-backend.onrender.com` |                                 |
| `ENVIRONMENT_NAME`     | `production`                                                         |                                 |
| `DJANGO_DEBUG`         | `False`                                                              |                                 |

**Handling Background Tasks (Celery) on Free Tier:**
Since Render doesn't offer free worker services, background tasks will fail to process if you don't have a worker.
**Option 1:** Avoid using background tasks for essential features, or set `CELERY_TASK_ALWAYS_EAGER = True` in your settings to execute tasks synchronously during the HTTP request.
**Option 2:** Use a free VPS like **Oracle Cloud Always Free** to deploy the entire stack using `docker-compose.prod.yml` instead of Render.

> **💡 Pro Tip:** To prevent your Render Free Web Service from going to sleep, sign up for a free uptime monitoring service like [cron-job.org](https://cron-job.org/) and set it to ping your backend URL `https://saas-backend.onrender.com/api/health/` every 10 minutes.

---

### Step 6: Frontend - Vercel or Render Static Sites (Free)

Host your React web app.

**Option 1: Vercel (Fastest Setup)**

1. Go to [Vercel](https://vercel.com) and connect your repo.
2. In the Vercel project configuration page, set the following:
   - **Root Directory:** `packages/webapp`
   - **Framework Preset:** Select **Vite** from the dropdown.
   - **Build Command:** `pnpm nx build webapp` _(Vercel runs this on their servers, do NOT run it locally)_
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

## Alternative Free Option: Oracle Cloud Always Free VPS

If you need Celery Background Workers and a complete replica of a paid deployment, the only truly free option is an **Oracle Cloud ARM VPS** (4 vCPUs, 24GB RAM).

1. Sign up for Oracle Cloud (requires a credit card for verification, but won't be charged).
2. Provision an Always Free Ampere A1 Compute instance (Ubuntu).
3. Install Docker and Docker Compose.
4. Clone your repository to the VPS.
5. Copy [`.env.vps.example`](./.env.vps.example) to `.env.prod` and fill it out (using free Neon/Upstash or running them locally on the VPS).
6. Run `docker compose -f docker-compose.prod.yml up -d`.
   _(Note: Oracle Cloud registrations are known to be difficult due to strict anti-fraud card checks, but it remains the most powerful free server available)._
