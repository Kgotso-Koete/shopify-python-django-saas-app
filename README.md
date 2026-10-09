<p align="center">
  <img src="./.github/images/saas-bp-logo.png" alt="SaaS Boilerplate powered by Apptension">
</p>

<h1 align="center">Build SaaS products faster in React, Django and AWS.</h1>
<h2 align="center">A complete SaaS starter kit based on a battle-tested stack with out-of-the-box features every SaaS should have</h2>

<h4 align="center">
  <a href="https://github.com/apptension/saas-boilerplate">
    <img src="https://img.shields.io/github/v/release/apptension/saas-boilerplate?style=for-the-badge" alt="Version">
  </a>

  <a href="https://github.com/apptension/saas-boilerplate">
    <img src="https://img.shields.io/github/license/apptension/saas-boilerplate?style=for-the-badge" alt="License">
  </a>

  <a href="https://twitter.com/apptension">
    <img src="https://img.shields.io/twitter/follow/apptension?style=for-the-badge&logo=twitter" alt="Follow Us on Twitter">
  </a>

  <a href="https://discord.apptension.com">
    <img src="https://img.shields.io/discord/1122849885335597088?style=for-the-badge&logo=discord" alt="Chat with us on Discord">
  </a>
</h4>

---

📖 [**SaaS Boilerplate Documentation**](https://docs.demo.saas.apptoku.com/)

🌟 [**SaaS Boilerplate Page**](https://www.apptension.com/saas-boilerplate?utm_source=readme-file&utm_medium=referral&utm_campaign=SaaS%20Boilerplate&utm_term=SaaS%20Boilerplate)

🚀 [**SaaS Boilerplate Demo**](https://app.demo.saas.apptoku.com/)

---

> ### 📚 LOCAL HOW-TO GUIDES — START HERE
>
> **The comprehensive development guides for this codebase live inside the repository at
> [`packages/internal/docs/docs/`](packages/internal/docs/docs/).** These cover
> GraphQL (queries, mutations, schema updates, fragments, error conventions),
> backend patterns (models, serializers, testing), frontend patterns (components,
> forms, routing), and much more. **Always check these guides before implementing
> a new feature or debugging an issue.**
>
> Quick links to key guides:
>
> - **[GraphQL overview](packages/internal/docs/docs/working-with-sb/graphql/index.mdx)** — how data flows between frontend and backend
> - **[Update GraphQL schema types](packages/internal/docs/docs/working-with-sb/graphql/web-app/update-schema.mdx)** — regenerate TypeScript types after backend changes
> - **[Add a backend mutation](packages/internal/docs/docs/working-with-sb/graphql/backend/adding-new-mutation.mdx)** — create new API endpoints
> - **[Create a backend model](packages/internal/docs/docs/working-with-sb/guides/backend/backend-model.mdx)** — Django model patterns

---

Supercharge your SaaS development with our comprehensive starter kit, designed to accelerate your project and save you
valuable time and resources. Our battle-tested boilerplate eliminates the need for extensive configuration and
development work, allowing you to focus on innovation from day one.

SaaS Boilerplate includes essential features that every SaaS application requires, such as frontend, backend API, admin
panel, and workers. With a scalable AWS-based architecture and continuous deployment, you can easily deploy multiple
environments representing different stages in your pipeline.

Say goodbye to weeks of setup and coding. Our proven stack and ready-to-use features empower you to jumpstart your
project and prioritize building your product's intellectual property. Unlock your SaaS potential faster than ever before
and seamlessly transition from setup to innovation.

## Keeping this fork in sync

This repository is a fork of [Apptension's SaaS Boilerplate](https://github.com/apptension/saas-boilerplate). To bring the latest commits from the original repository into this fork, add the original repository as an `upstream` remote once:

```sh
git remote add upstream https://github.com/apptension/saas-boilerplate.git
```

Then run the following commands whenever you want to sync the `master` branch:

```sh
git fetch upstream
git checkout master
git merge upstream/master
git push origin master
```

If Git reports merge conflicts, resolve them, stage the resolved files with `git add`, complete the merge commit, and then run `git push origin master`. Check `git status` first and commit or stash any local changes you want to keep before syncing.

## Getting started

### Requirements

- Install [Docker](https://docs.docker.com/get-docker)
- Install [Node.js](https://nodejs.org/en/download/) version 20 or above (which can be checked by running `node -v`).
  We recommend Node.js 20+ for optimal compatibility with the latest features. You can use [nvm](https://github.com/nvm-sh/nvm) or [n](https://github.com/tj/n) for managing multiple Node versions installed on a single machine.
- Install [pnpm](https://pnpm.io/installation) version 9 or above (which can be checked by running `pnpm --version`)
- (Windows only) Install [WSL 2](https://learn.microsoft.com/en-us/windows/wsl/install)

#### Optional

- Install [Python](https://www.python.org/downloads/) version 3.11 (which can be checked by running `python3 --version`) and [uv](https://docs.astral.sh/uv/getting-started/installation/) (which can be checked by running
  `uv --version`)
  - You need this one if you want to run `uv sync` command in `packages/backend` or `packages/workers` outside
    docker container
  - You can use [`pyenv`](https://github.com/pyenv/pyenv) for managing multiple Python versions installed on a single machine.

### Fresh installation

#### Setup using CLI starter kit

You can use a special CLI tool to run a new local instance of the SaaS Boilerplate as soon as possible. It will clone
the repository and take care of setting up the environment. Run the following command in the directory where you would
like to create a new project:

**_Using `npm`:_**

```bash
npm init saas-boilerplate PATH
```

**_Using `pnpm`:_**

```bash
pnpm create saas-boilerplate PATH
```

**_Using `yarn`:_**

```bash
yarn create saas-boilerplate PATH
```

> :information_source: Replace `PATH` with your desired project directory name (e.g., `my-saas-app`).
>
> :warning: **The target directory must be empty or non-existent!** The CLI will create it for you.

#### Manual setup

For the manual setup clone this repository and follow the steps in
[Getting started guide](https://docs.demo.saas.apptoku.com/getting-started/run-project/run-new-project#manual-setup).

### Run existing project

> :warning: **If you are using a Windows machine**, it's mandatory to have **WSL 2** (Windows Subsystem for Linux)
> installed on your system to run the commands for installing dependencies and running the application.

#### Clone the repository

```sh
git clone <your-project-repository-url>
cd <project-name>
```

#### Install dependencies

> ⚠️ **IMPORTANT: Node.js 20+ is required.** Before running any `pnpm` commands below, you must ensure you are using the correct Node version. Run the following command in your terminal:
>
> ```sh
> nvm install 20 && nvm use 20
> ```

The project is configured to use pnpm workspaces, which means that you can install `node_modules` of all packages in
repository, with single command:

```sh
pnpm install
```

> 💡 **Environment Files:** Make sure you have the necessary `.env` files from your team. If not, copy from `.env.shared` templates:
>
> ```sh
> cp .env.shared .env
> cp packages/backend/.env.shared packages/backend/.env
> ```

### Start the app

> ⚠️ **REMINDER: Ensure you are using Node 20 (`nvm use 20`) before running these `pnpm saas` commands!**

Start both: backend and webapp

```sh
pnpm saas up
```

#### Start backend

```sh
pnpm saas backend up
```

#### Start webapp

```sh
pnpm saas webapp up
```

#### Local documentation

In order to run your local documentation server execute following command:

```sh
pnpm saas docs up
```

#### Stop services

To stop all services:

```sh
pnpm saas down
```

### What's Running Locally?

After starting the application, you'll have these services available:

| Service         | URL                                                        | Description                |
| --------------- | ---------------------------------------------------------- | -------------------------- |
| **Web App**     | [http://localhost:3000](http://localhost:3000)             | Your SaaS frontend         |
| **Backend API** | [http://localhost:5001](http://localhost:5001)             | Django + GraphQL API       |
| **Admin Panel** | [http://admin.localhost:5001](http://admin.localhost:5001) | Django admin interface     |
| **Mailcatcher** | [http://localhost:1080](http://localhost:1080)             | Catches all emails locally |
| **Docs**        | [http://localhost:3006](http://localhost:3006)             | Local documentation        |
| **Workers**     | [http://localhost:3005](http://localhost:3005)             | Workers trigger server     |

> 💡 **First Steps:**
>
> 1. Open [http://localhost:3000](http://localhost:3000) and create an account
> 2. Check [http://localhost:1080](http://localhost:1080) for the verification email
> 3. Log in to the Admin Panel at [http://admin.localhost:5001](http://admin.localhost:5001) using credentials from your `.env` file

### Testing

Run these from the repository root. The backend tests run inside Docker, so Docker must be running; the frontend tests run on your machine (the web app isn't a Docker service).

#### Backend

The backend is one Nx project, so one command runs all its tests. It also runs the `black` formatter and the missing-migrations check first, as CI does:

```shell
pnpm nx run backend:test
```

One test file, or one test, in the backend container. `-e DATABASE_URL=` keeps the tests on the local database even if your `.env` points `DATABASE_URL` elsewhere:

```shell
docker compose run --rm -T -e DATABASE_URL= backend pytest apps/shopify/tests/test_views.py -v
docker compose run --rm -T -e DATABASE_URL= backend pytest apps/shopify/tests/test_views.py::test_install_view_disabled -v
```

#### Frontend

The frontend is 15 Nx projects (`webapp` and 14 libraries in `packages/webapp-libs`), each with its own `lint`, `type-check` and `test` targets, so each is run by name:

```shell
pnpm nx run webapp:test --watchAll=false
pnpm nx run webapp-core:test --watchAll=false
pnpm nx run webapp-finances:test --watchAll=false --testPathPattern=editSubscription
```

All frontend tests, one project at a time. `pnpm nx run-many` runs three projects at once by default, which can run a 16 GB machine out of memory. `--maxWorkers=2` limits each Jest run, and `--skip-nx-cache` makes Nx really run the tests instead of replaying an earlier result. Each project's output is saved to `logs/<project>.log` (the `logs/` folder is gitignored), and the terminal shows one exit code per project (`0` = passed):

```shell
mkdir -p logs; for p in webapp webapp-core webapp-tenants webapp-finances webapp-emails webapp-api-client webapp-contentful webapp-notifications webapp-crud-demo webapp-documents webapp-generative-ai webapp-sso webapp-ai-assistant webapp-backup; do pnpm nx run $p:test --watchAll=false --maxWorkers=2 --skip-nx-cache > logs/$p.log 2>&1; echo "$p test exit code: $?"; done
```

To see a project's test counts afterwards, for example `webapp-core`:

```shell
grep -E "Test Suites:|Tests:" logs/webapp-core.log
```

The full set (frontend lint and type-check, all tests, and the check that CI runs every library's tests), with logs saved to the gitignored `logs/` folder, is in section 8 of [`docs/superpowers/plans/2026-10-07-restore-green-test-suite-plan.md`](docs/superpowers/plans/2026-10-07-restore-green-test-suite-plan.md).

**All Packages:**

- `pnpm nx run-many --target=test`

### Commit Protocol

**1. Create a feature branch**

```shell
git checkout -b feature/<short-description>
```

**2. Update the changelog and bump the version**
Add an entry for the new version at the top of `CHANGELOG.md` (major for a breaking change, minor for a new feature, patch for fixes only). Then set that version in every `package.json` listed in `.versionrc.js`. `--skip.changelog` keeps your entry, `--skip.tag` leaves tagging until after the merge (step 6), and `--skip.commit` lets step 3 commit everything together.

```shell
npx standard-version --release-as X.Y.Z --skip.changelog --skip.tag --skip.commit
```

**3. Stage and commit your changes using [Conventional Commits](https://www.conventionalcommits.org/)**

```shell
git add .
git commit -m "feat(scope): brief description (vX.Y.Z)"
```

Common prefixes: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`

**4. Create a Pull Request**
Use the GitHub CLI to open a PR for review.

```shell
gh pr create --title "feat(scope): brief description" --body "Detailed explanation of changes."
```

**5. Merge and Delete Branch**
Once approved, squash and merge the PR, and automatically delete the feature branch.

```shell
gh pr merge --squash --delete-branch
```

**6. Tag the release**
Switch back to `master`, pull the merge commit, tag it with the version from step 2, and push the tag.

```shell
git checkout master
git pull
git tag X.Y.Z
git push origin X.Y.Z
```

## Features

<details open>
<summary>
This boilerplate includes plenty of ready to use features that you can adjust to your needs:
</summary> <br />

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/auth">
    <img src="./.github/images/features/auth.png" alt="Authentication and authorization" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/auth">Authentication and authorization</a>
    </summary><br/>
    <ul>
      <li>User registration and login, including Facebook and Google OAuth</li>
      <li>WebAuthn/Passkeys for passwordless authentication</li>
      <li>Enterprise SSO (SAML 2.0, OIDC) with SCIM 2.0 directory sync</li>
      <li>Basic user data like name, surname, and user role for authorization</li>
      <li>User email address verification via a transactional email</li>
      <li>Password change and password recovery within the app flow</li>
      <li>User management panel in Django admin</li>
      <li>Two-factor authentication (2FA)</li>
      <li>Active session management across devices</li>
    </ul>
  </details>

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/emails">
    <img src="./.github/images/features/emails.png" alt="Emails" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/emails">Emails</a>
    </summary><br/>
    <ul>
      <li>A set of ready-to-send transactional emails (new user verification, password recovery, subscription renewals, errors, etc.)</li>
      <li>Ability to schedule emails at a given time</li>
      <li>Sending test emails directly from a Storybook</li>
      <li>Internationalization support out of the box</li>
    </ul>
  </details>

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/payments">
    <img src="./.github/images/features/payments.png" alt="Payments" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/payments">Payments</a>
    </summary><br/>
    <ul>
      <li>Integration with Stripe services and its dashboard</li>
      <li>No customer payment method data is stored locally</li>
      <li>Support for multiple payment methods and their management (storing for future use and removal)</li>
    </ul>
  </details>

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/payments#subscription-management">
    <img src="./.github/images/features/subscriptions.png" alt="Subscriptions" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/payments#subscription-management">Subscriptions</a>
    </summary><br/>
    <ul>
      <li>Ability to charge users immediately or to set up recurring payments</li>
      <li>Subscription plans support and ability to freely modify current plans</li>
      <li>Free trial subscription plan, a grace period for credit card issues</li>
      <li>Superadmin panel enables customer management (i.e. refunds) without the Stripe dashboard</li>
    </ul>
  </details>

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/multi-tenancy">
    <img src="./.github/images/features/multitenancy.png" alt="Multi-tenancy" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/multi-tenancy">Multi-tenancy</a>
    </summary><br/>
    <ul>
      <li>Start immediately with a default tenant provided upon account creation</li>
      <li>Add new tenants as needed to manage multiple entities within a single account</li>
      <li>Utilize three default roles ”Owner, Admin, and Member” to control tenant activities and collaboration</li>
      <li>Securely invite and manage new members within each tenant</li>
    </ul>
  </details>

  <details open>
    <summary>
      Tenant backup and restore
    </summary><br/>
    <ul>
      <li>Per-tenant XML backups of selected modules and models</li>
      <li>Encryption of backup content (AWS Secrets Manager or DB fallback with <code>BACKUP_MASTER_KEY</code>); configurable schedule (interval and retention)</li>
      <li>Restore into the same or another tenant with conflict handling (skip, update, or fail)</li>
      <li>Email notifications when a backup is ready or fails, and when a restore completes or fails</li>
      <li>Backup/restore notification templates defined in the backup (tenants) module</li>
    </ul>
  </details>

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/cms">
    <img src="./.github/images/features/cms.png" alt="CMS integration (Contentful)" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/cms">CMS integration &#40;Contentful&#41;</a>
    </summary><br/>
    <ul>
      <li>Integration with Contentful service</li>
      <li>Example content model (image, title, and description)</li>
      <li>Ready to use CMS with a free plan</li>
    </ul>
  </details>

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/notifications">
    <img src="./.github/images/features/notifications/notification.png" alt="Notifications" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/notifications">Notifications</a>
    </summary><br/>
    <ul>
      <li>Real-time in-app notifications with WebSocket support</li>
      <li>Notification center UI with unread indicators</li>
      <li>Mark all as read functionality</li>
      <li>Easy to add new notification types</li>
    </ul>
  </details>

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/openai">
    <img src="./.github/images/features/generative-ai/saas-ideas.png" alt="AI Integration" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/openai">AI Integration</a>
    </summary><br/>
    <ul>
      <li>OpenAI integration ready for building AI-powered features</li>
      <li>Example implementation included</li>
      <li>Easy to extend with other AI providers</li>
    </ul>
  </details>

  <a href="https://docs.demo.saas.apptoku.com/introduction/features/crud">
    <img src="./.github/images/features/crud/list.png" alt="CRUD Generator" />
  </a>
  <br /><br />
  
  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/crud">CRUD Generator</a>
    </summary><br/>
    <ul>
      <li>Plop-based generators for quickly scaffolding new features</li>
      <li>Example CRUD module included</li>
      <li>Tenant-scoped data isolation</li>
      <li>Generate forms, tables, and GraphQL operations automatically</li>
    </ul>
  </details>

  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/management-dashboard">Management Dashboard</a>
    </summary><br/>
    <ul>
      <li>Complete financial management module (example module)</li>
      <li>Projects, iterations, revenue & cost tracking</li>
      <li>AI-powered CSV import with intelligent column mapping</li>
      <li>Financial forecasting with backtesting and scenarios</li>
      <li>Multi-currency support with FX rate management</li>
      <li>Excel-like timesheet with copy/paste and fill handle</li>
      <li>CFO Command Center with KPI dashboards</li>
    </ul>
  </details>

  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/rbac">RBAC Permissions</a>
    </summary><br/>
    <ul>
      <li>Fine-grained role-based access control</li>
      <li>Custom organization roles with color coding</li>
      <li>Permission categories (organization, members, security, billing, features)</li>
      <li>Frontend and backend permission enforcement</li>
    </ul>
  </details>

  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/activity-logs">Activity Logs</a>
    </summary><br/>
    <ul>
      <li>Comprehensive audit trail for all actions</li>
      <li>Field-level change tracking (old value → new value)</li>
      <li>Multiple actor types (User, AI Agent, System)</li>
      <li>Export to CSV for compliance</li>
    </ul>
  </details>

  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/ai-agent">AI Agent (MCP)</a>
    </summary><br/>
    <ul>
      <li>Model Context Protocol integration for AI assistants</li>
      <li>Natural language data queries and mutations</li>
      <li>RBAC-aware tool execution</li>
      <li>WebSocket streaming for real-time responses</li>
    </ul>
  </details>

  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/session-management">Session Management</a>
    </summary><br/>
    <ul>
      <li>Cross-origin cookie support for separate frontend/backend domains</li>
      <li>Safari/iOS authentication fallback with Authorization headers</li>
      <li>Multi-device session tracking and remote revocation</li>
      <li>Activity logging for authentication events</li>
    </ul>
  </details>

  <details open>
    <summary>
      <a href="https://docs.demo.saas.apptoku.com/introduction/features/storage-backends">Storage Backends</a>
    </summary><br/>
    <ul>
      <li>Flexible file storage with AWS S3, Cloudflare R2, Backblaze B2</li>
      <li>Dynamic backend selection based on environment</li>
      <li>Public and private storage separation</li>
      <li>CDN integration for translations and assets</li>
    </ul>
  </details>

---

</details>

... and more

The full list with the descriptions can be found in the [features documentation](https://docs.demo.saas.apptoku.com/introduction/features/).

## Tech stack

Front-end stack:

- [React](https://github.com/facebook/react) 19.2.x
- [TypeScript](https://www.typescriptlang.org/) 5.4.x
- [GraphQL](https://graphql.org/)
- [Apollo Client](https://github.com/apollographql/apollo-client) 4.x
- [React Router](https://github.com/remix-run/react-router) 7.x
- [Vite](https://github.com/vitejs/vite) 6.x
- [tailwindcss](https://github.com/tailwindlabs/tailwindcss) 3.4.x
- [shadcn/ui](https://github.com/shadcn-ui/ui)
- [jest](https://github.com/jestjs/jest)
- [Storybook](https://github.com/storybookjs/storybook) 10.x

> ℹ️ **Styling Approach:** **Tailwind CSS** is the primary styling solution for all components. Use Tailwind utility classes with the `cn()` helper for conditional styling. [styled-components](https://github.com/styled-components/styled-components) is included as a dependency for internal theme infrastructure and email template rendering, but developers should use Tailwind CSS for all new component styling. See the [shadcn/ui guide](https://docs.demo.saas.apptoku.com/working-with-sb/shadcn) for component styling patterns.

Back-end stack:

- [Python](https://www.python.org/) 3.11.x
- [Django](https://github.com/django/django) 5.2.x
- [Django REST Framework](https://github.com/encode/django-rest-framework) 3.15.x
- [Graphene Django](https://github.com/graphql-python/graphene) 3.2.x
- [Celery](https://github.com/celery/celery) 5.4.x
- [Sentry SDK](https://github.com/getsentry/sentry-python) 2.0.x
- [dj-stripe](https://github.com/dj-stripe/dj-stripe/)
- [Postgres](https://www.postgresql.org/) 14+
- [Redis](https://redis.io/) 7+

Infrastructure:

- [NX](https://github.com/nrwl/nx) 19.x
- AWS infrastructure written in [AWS CDK](https://github.com/aws/aws-cdk) 2.x
- [Docker](https://www.docker.com/) (Latest)
- [pnpm](https://pnpm.io/) 9+ (package manager)
- GitHub or Bitbucket

3rd party services:

- Stripe
- Contentful
- Sentry
- SonarCloud
- OpenAI

The [detailed stack description](https://docs.demo.saas.apptoku.com/introduction/stack-description) is available in the documentation.

## How was the SaaS Boilerplate created?

In our experience in Apptension, we have built hundreds of web and mobile applications over the years and saw a bunch of standard features. For example, all applications (or at least 99% of them) need a login, email templating, payments and subscriptions, CMS integration, and more.

A broader list of elements that can be implemented in projects in this way was created after building dozens of different types of SaaS products. We analyzed them and noticed many common parts appeared virtually unchanged. So we created SaaS Boilerplate that is the base, and while it requires design or functional customization for a specific SaaS product, it dramatically reduces development time.

That's why you don't have to start by writing the code for that login or payment function. Instead, you can use off-the-shelf elements in those places and focus on creating the rest of the features unique to the project.

The development process is ongoing as we continually add new features and improve existing ones. We started with AWS Boilerplate, which evolved into the current SaaS Boilerplate. It originally contained only infrastructure (a configured AWS account) and was a template for the project, which had blanks for the back-end and front-end.

We saw that it was already a handy and very well-received tool, so the next natural step was to add more elements to it – front-end, back-end, and pack the relevant features that were most often repeated in different projects, including logging, CRUD, payments, integration with content pool, etc.

Our idea was that it shouldn't be just the code itself because SaaS Boilerplate also contains our know-how – because we gathered everything needed for development and around development in one package. So you don't have to think about choosing code formatting, matching different tools and their subsequent configuration, etc. Moreover, such a package is proven and battle-tested – you can just upload it to the cloud and start so-called heavy development.

## Who are we?

We're [Apptension](https://apptension.com?utm_source=readme-file&utm_medium=referral&utm_campaign=SaaS%20Boilerplate&utm_term=SaaS%20Boilerplate), a team that turns ideas into world-class software using expertise in technology, design, and product management. We work with founders, investors, and creative agencies to help them bring uncommon ideas to the market.

Our partners value our outside-the-box thinking, clear and honest communication, and reliability – even in the most dynamic and time-compressed projects. Among our clients – plenty of early-stage startups, as well as international tech behemoths like Netflix and Uber. We live and breathe tech – and we're darn good at it.

To bring even more value to our partners, we create bespoke tools (like SaaS Boilerplate), allowing us to shorten time-to-market while avoiding technical debt.

## License

SaaS Boilerplate is licensed under the [MIT License](./LICENSE).

## Contributing to SaaS Boilerplate

We welcome contributions from anyone interested in improving SaaS Boilerplate. Please keep in mind that this project follows a [Code of Conduct](./CODE_OF_CONDUCT.md) to ensure a welcoming community for all.

For more detailed information on how to contribute to this project, please refer to our [Contributing Guide](./CONTRIBUTING.md).

If you have any questions about contributing, please join our [Discord server](https://discord.apptension.com) - we are happy to help you!

Thank you for considering contributing to SaaS Boilerplate!
