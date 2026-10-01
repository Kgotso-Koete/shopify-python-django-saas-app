# Working agreement: the human maintainer and AI coding agents

## Purpose of this codebase

Every rule in this document exists because of what this codebase is for, so read this first.

- **It is a public (for now; it is expected to become private later), open-source fork of the Apptension SaaS Boilerplate** (https://github.com/apptension/saas-boilerplate), published at https://github.com/Kgotso-Koete/shopify-python-django-saas-app. The stack is an Nx monorepo managed with pnpm: Django + Graphene GraphQL (`packages/backend`), Celery (`packages/workers`), React (`packages/webapp`, `packages/webapp-libs`), AWS CDK (`packages/infra`) and an MCP server (`packages/mcp-server`). It extends the upstream boilerplate with production-grade capabilities, one building block at a time. An example is PayFast payments alongside Stripe (`docs/superpowers/plans/2026-09-30-payfast-payment-backend-plan.md`). The fork is kept in sync with upstream by merging `upstream/master`, as the README's "Keeping this fork in sync" section describes. That is one more reason every addition stays additive (section 3).
- **It is built to help maintainers of commercial and hobby projects small enough to be built and maintained by a solo developer.** It helps them solve the complexity, maintainability, testability and other technical debt problems such projects run into as they grow: a codebase one person can still understand, change safely and keep healthy years later. Real products, commercial or hobby, are built on it through private forks. So it has to stay generic, and small enough for one developer to run, understand and afford: the smallest viable infrastructure by default, with heavier infrastructure as an optional upgrade.
- **It builds comprehensive, production-ready vertical slices that many applications can build on and depend on.** A vertical slice is a capability built all the way through the stack, from domain and use cases to persistence, HTTP and tests, finished to production quality rather than sketched. The slices this codebase provides are the ones nearly every application needs:
  - user-scoped use cases: accounts, authentication, profiles, sessions
  - organization-scoped use cases: tenants, memberships, invitations, roles and permissions
  - billing use cases: subscriptions, payments and donations, with Stripe or PayFast behind `PAYMENT_BACKEND`
  - notification use cases: in-app notifications, email and similar delivery

  Any other vertical slice, and any business-specific logic, belongs in the products built on top, not here. It is added only when the human maintainer explicitly asks for it, or has specified it in a plan in `docs/superpowers/plans/` (see 4.5).

- **It exists to solve small-scale architectural, complexity and maintainability problems properly.** The value of this codebase is its discipline: the existing Django-app and Nx-library structure, explicit design decisions, and every behavior pinned by a test. A shortcut that makes something work while eroding that discipline defeats the purpose of the codebase, even when the feature appears to work.
- **It is also how the human maintainer learns and masters a complex system.** The human maintainer extends it with an AI agent as a pair programmer. When a person is learning a system, changing pieces whose consequences they don't fully understand is exactly how subtle, hard-to-predict breakage gets in. Adding self-contained, well-explained, well-tested pieces lets them reason about each addition on its own.

That purpose is why the rules below look the way they do:

- **strict TDD and never bypassing checks:** the discipline is the product.
- **additive building blocks, small diffs, and extra care with the original author's code:** don't break trusted code, and let a learner reason about additions in isolation.
- **the smallest viable infrastructure:** a template one developer can run, understand and afford.
- **explaining code before showing it, and commenting liberally:** learning.
- **plans in the repository, and this document as the source of truth:** AI agents forget between sessions; the repository doesn't.
- **keeping examples generic and never leaking a private fork:** a public template.
- **complete, production-ready slices, and no business-specific logic:** a foundation many different applications can depend on.

## About this document

This document lists the standing rules for how the human maintainer of this repository and an AI coding agent work together on it. Each rule was set, or corrected, by the human maintainer during real pair-programming sessions. Each one records the rule, the reason for it, and how to apply it, so a new session, or a new agent, can follow it without having to relearn it the hard way.

These rules apply to all work in this codebase, not to one feature. When a rule and an AI agent's own default habits disagree, the rule wins.

**This document is the only source of truth for the rules an AI agent follows in this codebase.** An AI agent may also keep its own notes about these rules in whatever persistence its tool offers (saved memories, custom instructions, rules files, project settings), but those notes must always stay in sync with this document:

- Whenever the human maintainer sets or corrects a rule, the AI agent updates this document in the same change as its own notes.
- If the two ever disagree, this document wins, and the AI agent fixes its notes to match.
- A rule that exists only in an AI agent's private notes, and not here, is not a rule of this codebase.
- `CLAUDE.md` at the repository root holds the **dev flow bindings**: the concrete values for this repo, such as default branch, commit convention, verification commands and project board. It doesn't hold working rules. Where a binding and a rule here overlap (for example, the verification commands), they must agree. When one changes, update the other in the same change.

## Who is who

This document refers to three distinct parties. They are never interchangeable.

- **The human maintainer** is the person who owns this repository and is in charge of it. They decide its composition (what gets built, and in what order), orchestrate the work (which step comes next, when a RED or GREEN is confirmed, when something is committed and merged), and make the architecture and design calls. They are accountable for everything that lands in the codebase. They run every command, approve every change, and are the only party who can grant an exception to any rule below.
- **The AI agent** is whichever AI coding assistant is pair-programming with the human maintainer in a given session, whatever the tool, model or vendor. Every rule here applies to any AI agent equally. It proposes designs, writes tests and code within these rules, explains what it writes, and hands commands to the human maintainer to run. It never decides on its own to relax a rule, and it keeps no memory between sessions except what's written down (this document, the plans in `docs/superpowers/plans/`, the specs in `docs/superpowers/specs/`, and its own saved notes).
- **The original author** is Apptension, the team behind the upstream SaaS Boilerplate this repository was forked from (https://github.com/apptension/saas-boilerplate). They are not a participant in these sessions. "The original author's code" means everything that came from upstream, including what later `upstream/master` merges bring in, as opposed to what the human maintainer and the AI agent added. Section 3 explains why that code is handled with extra care.

---

## 1. Commands and execution

### 1.1 The human maintainer runs every command

The human maintainer runs every terminal command (shell, git, docker, pnpm, nx, uv, pytest, and so on) unless they explicitly say otherwise for a specific command. The AI agent does not run commands itself. It hands over the exact command to run, with a short explanation of what that command does, so the human maintainer understands it before running it.

- This holds whatever permission or autonomy setting the AI agent's tool is running under. An auto-approving mode, or earlier commands in the same session that ran without objection, is never authorization to keep running commands. Such settings change how much the AI agent can decide without asking; they do not change who runs commands.
- Read-only commands (`ls`, `grep`, `cat`, `find`) are not exempt. To inspect the codebase, the AI agent uses its tool's built-in file-reading and search features, not shell commands.
- **When the human maintainer does authorize a specific command** ("run the command", "just do it"), the AI agent runs it immediately, in that same turn, with no re-explaining, hedging or second confirmation.
- **Standing exception: fetching past conversation text.** When the human maintainer asks for messages from a previous session, or the exact text of an earlier message, the AI agent retrieves it itself straight away (see section 8).

### 1.2 Use the real entrypoint for verification

When giving manual verification steps, use the real top-level command a user or a deployment would run (a documented `pnpm saas` command, an Nx target), not a hand-built sequence of its internal sub-steps. Examples: `pnpm saas down` then `pnpm saas up`, not a hand-picked `docker compose up` of individual services; and `pnpm nx run backend:test`, not a bare `pytest`, because the Nx target also runs the formatter and the migrations check. Verification should exercise the whole real workflow, not an approximation that happens to reach the same state.

### 1.3 The verification ladder

- **RED step:** run the single test file.
  - Backend: `docker compose run --rm -T backend pytest <path> -v`. Tests run in the backend container against its Postgres, and `setup.cfg` loads `.test.env`.
  - Frontend: `pnpm nx run <project>:test --watchAll=false --testPathPattern=<path>`, e.g. project `webapp-finances`.

  A RED has to be seen as a running test failure. Lint and type-check stop before any test runs, so they can't show a RED.

- **GREEN step:** run the project's full Nx targets, not just the single file.
  - Backend: `pnpm nx run backend:test`. It runs `ruff check` (report-only), `black`, `manage.py makemigrations --check --dry-run`, then the whole pytest suite with coverage.
  - Frontend: `pnpm nx run <project>:lint`, `pnpm nx run <project>:type-check` and `pnpm nx run <project>:test --watchAll=false`, for every Nx project touched.

  These are the same targets CI runs (`.github/workflows/backend.yml`, `.github/workflows/webapp.yml`). They catch a GREEN whose tests pass but that breaks a type, a lint rule, formatting or a missing migration.

- **Anything touching infrastructure (Postgres, Redis, Celery, the worker, external APIs such as Stripe or PayFast):** run the GREEN targets, then start the whole stack with `pnpm saas up`, and only then do manual checks. Don't skip the automated tier.
- **The final and ultimate check: simple, human-driven, common-sense verification.** Automated tests prove what they were written to prove. The last rung is a small list of manual checks the human maintainer can do and see for themselves, without complex container workflows or reading test output:
  - a click-through in the browser, or a request from Postman
  - an AI-assisted `curl` command
  - looking at the response or the page
  - confirming it matches what a user would expect

  Every feature's verification plan ends with such a list. Keep it short (a handful of checks) and concrete: the exact request, and what a correct result looks like, so anyone can sense-check it in a few minutes.

- **Seed data comes before the human check, not after it.** Most human checks run against data that seed commands have already created: named accounts, tenants, roles and every interesting state (pending, expired, accepted, and so on). The repository has no general seed script yet. Seed data is added as an idempotent Django management command in the app it belongs to, run with `docker compose run --rm backend python manage.py <command>`, following the existing `init_customers_plans` and `init_subscriptions` commands. The human maintainer creates only a little data by hand, to exercise the create/update/delete paths themselves. So whenever a slice becomes reachable by a human (its routes exist), the seed data for it is added in that same step, before the human check is handed over. It is never deferred to the end of the plan. An AI-assisted human check that makes the human build all the test data from scratch has missed the point.
- **Human checks are written down in the feature's plan, as copy-pasteable commands or click paths.** Each check is a numbered item in a "Human checks" section of that feature's plan in `docs/superpowers/plans/`. It gives which seeded account it acts as, the expected result, and one of:
  - for a UI flow, the exact click path in the web app (http://localhost:3000)
  - for an HTTP endpoint (a webhook such as the PayFast ITN, the REST API, or the GraphQL API at `/api/graphql/`), the exact, human-readable `curl` command, with a login step and one cookie file per user where needed The checks live in the plan, not only in chat, so they survive between sessions and can be re-run at any time. Aim for 5 to 20 checks per step. Seeded rows the checks act on get fixed ids, so the commands can be pasted as written.

### 1.4 Git follows the documented protocol exactly

When committing, pushing or opening a PR, follow the repository's documented protocol and nothing more. It's recorded in `CONTRIBUTING.md` and the `CLAUDE.md` dev flow bindings:

- GitHub Flow: a feature branch off `master`, then a pull request based on `master`.
- Conventional Commits (`feat(scope): brief description`, `fix(scope): …`, `docs: …`, and so on).

Give the human maintainer exactly the branch, `git add`/`git commit`, `gh pr create` and `gh pr merge --squash --delete-branch` commands. Don't add extra steps, elaborate heredoc bodies or inferred prerequisites. If a genuinely necessary step is missing, mention it briefly and mark it as an addition.

Every commit includes its release bookkeeping; a commit with only code is incomplete:

- **The commit message is the changelog entry.** `CHANGELOG.md` is generated by `standard-version` from Conventional Commit messages (configured in `.versionrc.js`), so don't hand-edit it in a feature commit. The commit type decides where the change appears: `feat` goes under Features, `fix` under Bug Fixes and `deps` under Dependencies, while `chore`, `docs`, `style`, `refactor`, `perf` and `test` are hidden. So choose the type, the scope and a subject that says what changed and why, and put details in the body.
- **Version bumps happen at release, not per commit.** `standard-version` bumps every `package.json` listed in `.versionrc.js`, and `RELEASE_PLAN.md` documents the release process. Don't put a version number in a feature commit's message.
- Any other release step a plan in `docs/superpowers/plans/` documents.

The AI agent drafts the commit message (and PR description) alongside the code, for the human maintainer to review, rather than leaving it to be remembered at commit time.

**The pre-commit hook.** `.husky/pre-commit` runs `lint-staged` (configured in `.lintstagedrc`): `eslint --fix` on staged `*.ts`/`*.tsx`, and `prettier --write` on staged `*.json`/`*.md`/`*.html`. It needs `node_modules` (run `pnpm install` first), and on a fresh clone it builds the Nx graph once. Two consequences:

- The hook may rewrite staged files. Review what it changed before pushing; don't blindly re-stage.
- The hook doesn't check Python. Python formatting (`black`) and linting (`ruff`) only run inside `pnpm nx run backend:test`, so run that target before committing any backend change. Don't rely on CI to catch it.

Never bypass the repository's safeguards to get a commit or push through: no `--no-verify` to skip pre-commit hooks, no setting `CI=1` locally to make the hook exit early, no `--force` pushes, no skipping or silencing a failing check. When a hook or check fails, the failure is information; fix what it found. See 4.4.

---

## 2. Test-driven development (red, green, refactor)

### 2.1 Never write production code before its test

This is a codebase-wide rule with no feature boundary. Production code at any layer is never written before a test that exercises it exists and has been run to a confirmed failure. That includes models, choices and constants, managers, service functions, external API clients, serializers, GraphQL types, queries and mutations, webhook views, URL routes, Celery tasks, React components and hooks, and the wiring that registers them (`INSTALLED_APPS`, `config/schema.py`, `config/urls_api.py`, route switches).

The sequence for every step:

1. **Write the test file only.**
2. **Stop and hand over the command to run it.** The human maintainer runs it and confirms it fails for the expected reason: an import error, a missing attribute, a 404 or 405 from an unmounted route, a GraphQL "Cannot query field" error from an unregistered field, or an assertion failing against behavior that isn't implemented yet. This is RED, and it has to be observed, not assumed.
3. **Only after RED is confirmed,** write the minimal production code that makes it pass, then hand over the command again for the human maintainer to confirm GREEN.
4. **Only after GREEN is confirmed,** refactor, keeping the tests green.

Never write a test and its production code back to back in the same turn.

The only exceptions:

- **Code that is genuinely not worth testing,** such as trivial one-line wiring with no behavior of its own. This is the human maintainer's call, never the AI agent's. The AI agent must not decide on its own that something is untestable.
- **An explicit green light from the human maintainer** for one specific piece of code.

**Test-support code is not itself tested.** Unit and integration tests are for application code. Seed commands (see 1.3), test factories (`apps/*/tests/factories.py`), fixtures and test helpers are part of the testing _methods_, not application code: a seed script supports manual testing the way a fixture supports automated testing. Tests are not tested by other tests, and the same goes for seed scripts. They are written directly, without a RED/GREEN cycle.

**Interfaces are not exempt.** A dispatch function, an API client class, a model or a GraphQL type is introduced in the same TDD cycle as the first test that needs it: the client's own unit test with the HTTP layer mocked, or a consumer's unit test. The missing module is part of that test's RED. Never write one as a standalone step "because it has no behavior".

### 2.2 Keep REDs simple, and never suppress tests

- **A RED must be a running test failure.** Never propose a RED that relies on `type-check`, `lint`, `makemigrations --check` or any other step that stops the unit tests from running. The human maintainer's words: "Unit tests must always run, I don't want anything to suppress unit tests."
- **Design choices and constants before the models and services that hold them.** A model's first test should already expect its `TextChoices` or constants type (the way `apps/finances/constants.py` defines `SubscriptionPlanConfig` before anything uses it), so the RED is the ordinary "module or type doesn't exist yet" failure, and GREEN is creating the model with the correct type.
- **If choices or a type are retrofitted onto an existing field,** treat it as the simple change it is: update the tests to expect them, change the field and generate the migration, and run the suite. Don't invent an elaborate RED for a type annotation.

### 2.3 New settings need a loader test

Every new environment-variable-driven setting (read with `env(...)` in `packages/backend/config/settings.py`, or `process.env.VITE_*` in `webapp-core/src/config/env.ts`) needs two kinds of test:

1. the consuming code's own unit tests, using plain literal values through `override_settings` (or a mocked `ENV`) for its internal logic
2. a dedicated `test_<name>_setting_reads_env_var` test in the consuming app's `tests/`, proving the setting really reads the environment variable. For backend settings, import `config.settings` in a **fresh subprocess** with the variable set, and assert on the value. Settings are evaluated once at import, so reloading them inside the running test process would disturb every other test.

A hardcoded literal in the consumer's tests alone leaves the environment-variable wiring completely unverified.

### 2.4 One continuous push, one micro-step at a time

For a large, multi-step plan, the human maintainer prefers one continuous session over splitting the work across several PRs or sessions, because an AI agent loses context between sessions. The discipline inside that push is still strict TDD: one step, one test, a confirmed RED, a confirmed GREEN.

---

## 3. Changing existing code

### 3.1 Additive building blocks only

Never tamper with existing code whose full consequences aren't understood. That especially means the original template author's code, and earlier features the human maintainer already built and trusts. New functionality is added as a self-contained building block on top of the existing composition, not by restructuring or reaching into it, even when the restructuring would preserve behavior and be technically cleaner.

- **The "feature delete" test:** it should be possible to delete what was just added and get the original composition back completely unaltered. If deleting the addition would also mean undoing changes to existing files, the work has strayed into risky territory.
- **Prefer a little duplication over editing an existing class** to fit a new use case. The model is PayFast: a new `apps.payfast` Django app and a `webapp-finances/src/payfast/` folder, added beside the Stripe code in `apps.finances` without rewriting it, with a thin dispatch module choosing between them.
- **The limit in the other direction:** some upstream files are composition points that every feature must register in: `INSTALLED_APPS` and `CELERY_BEAT_SCHEDULE` in `config/settings.py`, the `Query`/`Mutation` lists in `config/schema.py`, `config/urls_api.py`, the routes in `packages/webapp/src/app/app.component.tsx`, and `webapp-finances/src/routes/index.tsx`. Appending a few lines there is fine. Still flag it as a touch to an original file, and never restructure, split or reorder the existing entries.
- **Upstream merges are the second reason.** Every changed line in an upstream file is a possible conflict the next time `upstream/master` is merged. A small, additive footprint in upstream files keeps those merges cheap.

The reasoning: the original author's code is, right now, at the highest quality and the most battle-tested it will ever be. Every edit is a chance to introduce a regression into code that has none.

### 3.2 Keep the diff small

When editing an existing file, use targeted edits (one per site, or a replace-all for a truly uniform rename), not a full-file rewrite. A wholesale rewrite hides which lines actually changed and invites accidental drift. Full-file writes are for new files, or a rewrite the human maintainer asked for.

### 3.3 Don't rewrite human-authored comments or prose

When a change makes part of an existing comment or document stale, fix only the specific detail that changed, or add a small note next to it. Don't regenerate the surrounding human-written prose, even if the rewrite would also be accurate. Rephrasing text that was already correct risks introducing new, subtle errors.

### 3.4 Don't "correct" the original author's instructions

Never edit the original author's documented commands or setup steps (in `README.md` or similar) because they look like a bug, even when the reasoning seems solid. The original author has years of context an AI agent reading the code fresh doesn't have, and the original author often turns out to be right. Raise the discrepancy in conversation for the human maintainer to decide. New docs that describe the same command should mirror the author's text literally.

### 3.5 Audit privilege before sharing a capability across entrypoints

Before exposing a capability on another entrypoint, or reusing a precedent's permissions by pattern-matching, check two things. The entrypoints are the GraphQL API (cookie JWT), the REST API, the Django admin, the MCP server (`packages/mcp-server`), and public webhooks (Stripe, PayFast ITN). A typical precedent is copying `permission_classes(IsTenantMemberAccess, requires("billing.view"))` from a neighbouring resolver.

1. **Would it retire or touch an implementation that already works on either entrypoint?** If so, don't, unless there's a strong reason argued separately.
2. **Do that entrypoint's real use cases and privilege model justify the capability?** A tenant member with `billing.view` is not a billing manager, and an MCP or webhook caller is a narrow, programmatic one. Letting a read-only role start a payment, or trusting a field a webhook sender controls (such as a tenant id in `custom_str2`), is a far larger privilege than the entrypoint should allow. `AnyoneFullAccess` in particular is reserved for data that is genuinely public.

---

## 4. Design principles

### 4.1 Smallest viable infrastructure by default

Every capability must work on the infrastructure the project already runs: the services in `docker-compose.yml` locally, and the zero-cost deployment in `render.yaml`. A new paid service or third-party dependency is an optional, switch-on upgrade selected by an environment variable, never mandatory for a core capability. Extra infrastructure costs real money.

- **Choose the mechanism by configuration.** Ship a default that needs nothing new, and make the heavier or alternative implementation a second one selected by a setting.
- **The default must be genuinely correct, not a toy.** An in-process memory counter isn't shared across web workers or Celery processes, for instance, so a Postgres-backed one is the honest default.
- **The models to copy:** `PAYMENT_BACKEND` (Stripe or PayFast behind the same app behaviour), `STRIPE_ENABLED`, and the env-controlled Contentful and translation syncs, which only join `CELERY_BEAT_SCHEDULE` when switched on.

### 4.2 Follow the existing project structure

Every implementation plan follows the structure the upstream code already uses:

- **Backend:** one Django app per capability under `packages/backend/apps/`. Each app has `models.py`, `managers.py`, `services/` (business logic), `serializers.py`, `schema.py` (Graphene types, queries and mutations), `webhooks.py`/`views.py`, `urls.py`, `tasks.py`, `admin.py` and `tests/`. Shared code goes in `common/`, and the composition root is `config/`. Business logic goes in services, not in resolvers or views, and an app doesn't reach into another app's internals when a service function exists.
- **Frontend:** code lives in the Nx libraries under `packages/webapp-libs/` and is imported through their public entry points. The `@nx/enforce-module-boundaries` ESLint rule enforces this, and it is never silenced.
- **GraphQL contract:** after a schema change, regenerate the committed schema and types with `pnpm nx run webapp-api-client:graphql:download-schema`, and commit them in the same change as the backend code.

### 4.3 Naming in the DI layer

Classify which of three layers something sits in before naming it:

1. **Generic entry points** that callers use stay mechanism-neutral: `billing.initialize_tenant`, `billing.cancel_tenant_subscription`.
2. **Concrete implementations** are named after their mechanism or provider, not the caller that uses them: `PayFastApiClient`, `apps.payfast`, `StripePaymentForm`. A second mechanism then becomes a new sibling, and the first one's name stays accurate.
3. **Composition points** are named after what they wire: `config/schema.py`, `config/urls_api.py`, a route switcher such as `paymentBackendSwitch`.

### 4.4 Never take the path of least resistance

This codebase exists to solve small-scale architectural and complexity problems properly. Taking the path of least resistance is never the answer unless the human maintainer explicitly allows or asks for it. When the disciplined way and the quick way differ, take the disciplined way, or stop and ask.

Examples of what this rules out:

- forcing a commit or push past failing pre-commit hooks or checks (`--no-verify`, `--force`)
- skipping a test, or writing code before its test
- suppressing a type or lint error (`# noqa`, `# type: ignore`, `eslint-disable`, `@ts-ignore`) instead of fixing its cause
- weakening an assertion until it passes
- hardcoding a value that should come from configuration
- cutting a layer or Nx module boundary "just this once"

TDD and the automated checks are core to this repository's design, so working around them works against the very thing the codebase is meant to demonstrate.

### 4.5 Build generic vertical slices, not business logic

Features in this codebase are comprehensive, production-ready vertical slices that many applications can build on: user-scoped, organization-scoped, billing and notification use cases. Each slice is finished through every layer, with tests, error handling, authorization and documentation, rather than left as a demo.

- **Don't add any other vertical slice, or any business-specific logic** (rules, entities or workflows that only make sense for one kind of product), unless the human maintainer explicitly asks for it or has specified it in a plan in `docs/superpowers/plans/`. A plan the human maintainer wrote or approved counts as specifying it; an AI agent's own suggestion doesn't count until the human maintainer approves it.
- **When an example resource is needed** to show a pattern, keep it deliberately generic and minimal, like the upstream CRUD demo items (`apps/demo`, `webapp-crud-demo`) or the donation example in `webapp-finances`.
- **Before proposing a feature,** check that it would be useful to many different applications. If it would only be useful to one product, it belongs in that product's fork, not here.
- **A slice includes seed data, not just tests.** Besides its unit, integration and smoke tests, every vertical slice adds development seed data to the database (via an idempotent management command, see 1.3). A human reviewer or tester can then try the feature by hand, or demo it, straight after `pnpm saas up`, without first building up state themselves. Seed data covers the interesting cases, not just the happy path: for example an expired key as well as a valid one, or a pending invitation as well as an accepted membership. It pairs with the human-driven checks in 1.3, which should be runnable against the seeded data.

### 4.6 Every addition is a liability

Every line of code, every file, every document and every comment is a liability. Each one increases the surface area for bugs and complexity, and adds cognitive load for the human who has to review, understand and maintain it. The human maintainer's attention is the ultimate bottleneck of this whole way of working, more than an AI agent's speed or output, so information is added with care.

- **Before adding anything, ask whether it earns its place.** Does it make the system more correct, or make it easier for a human to understand? If not, leave it out.
- **Prefer the smallest change that fully solves the problem,** and the shortest wording that fully explains it. Remove what's redundant rather than piling on more.
- **Weigh it at review time too.** A large diff, a new file or a long explanation spends the human maintainer's attention, so it has to be worth that cost.
- **Being a liability doesn't mean "don't add".** Code is a liability too, and we still write it whenever a feature needs it. The point is to add deliberately, not to add less at all costs. Once a feature is decided, the code, tests, seed data and comments that feature needs are all worth their cost. Not all additions weigh the same: application logic carries the most risk, and comments the least, because they are not logic (see 5.1).

---

## 5. Code style

### 5.1 Comment liberally

Add explanatory comments wherever possible, in application code and test code alike, even for things a well-named identifier would normally make obvious. This intentionally departs from a sparse-comment default.

This doesn't conflict with 4.6. Once we decide to build feature X, the code for X is worth adding, and so are the comments that explain it. A comment is a liability like any other addition, but a smaller one than code, because it isn't application logic.

Code is the ideal form of documentation and of design intent. But code is best understood in relation to other code: the rest of its module, the port it implements, the use case that calls it. A reader meeting one function for the first time doesn't have that context yet. Comments supply it. They help a human understand a function before meeting the rest of its family of functions, which lowers the cognitive load of reading the code rather than adding to it.

### 5.2 Explain code before showing it

Whenever the AI agent proposes code for review, it explains what the code does in three places: in the code's own design and structure, in code comments, and in the chat message. The chat explanation comes _before_ the diff, so the human maintainer never has to reverse-engineer intent from a wall of changed lines.

### 5.3 Exact-pin every new dependency

Every dependency the human maintainer and the AI agent add is pinned exactly.

- **Python:** `==` in `packages/backend/pyproject.toml`, runtime and dev groups alike. After `uv add`, immediately tighten the constraint to the exact version resolved in `uv.lock`.
- **JavaScript:** an exact version with no `^` or `~` in the relevant `package.json`, added with `pnpm add --save-exact --filter <project>`.

Upstream's existing constraints are mixed (`==`, `~=`, `>=`, `^`). Leave them as they are (section 3), because re-pinning them would conflict with every upstream merge. Check this whenever the dependency lists are touched.

### 5.4 Docker Compose variables always have a fallback

Every environment variable we add to a `docker-compose*.yml` file uses `${VAR:-default}`, never a bare `${VAR}`. The default is the value that was hardcoded there before the variable existed, so a missing or incomplete `.env` degrades gracefully instead of producing a broken configuration. Upstream's existing bare variables (such as `${PROJECT_NAME}`) are left alone (section 3). The same idea applies to Django settings: every new `env(...)` call gets a `default=` that keeps the app working, as the PayFast settings do.

### 5.5 Fix the content, not the linter config

When a linter or spellchecker flags a false positive, fix the content that triggered it (reword the prose, rename the identifier) rather than adding a new suppression or config file. A new config file is one more thing to maintain forever.

---

## 6. Plans and documentation

### 6.1 Plans live in `docs/superpowers/plans/`

Implementation plans are saved as markdown under `docs/superpowers/plans/`, named `YYYY-MM-DD-<topic>-plan.md`. Design specs that come before a plan go under `docs/superpowers/specs/`, named `YYYY-MM-DD-<topic>-design.md`. Plans follow the established structure:

- a "Proposed Changes" section of numbered steps, each listing the test files to write first and the production files to change second
- a File Summary
- a Verification Plan: automated tests, the GREEN targets from 1.3 (`backend:test`, `<project>:lint`, `<project>:type-check`, `<project>:test`), and ending with the short list of simple human-driven checks from 1.3

Whenever an AI agent creates a plan, it always externalizes it as a file in `docs/superpowers/plans/` so it survives across sessions. The plan file in this codebase is the single source of truth, not the ephemeral plan in the AI agent's own tools (such as a plan-mode draft or a to-do list), which disappears when the session ends. Read from the file and write updates to it, never to a draft held elsewhere or only in the conversation. Good test coverage is a stated goal of every plan, not an afterthought.

Two further sections belong in every plan where they apply, including older plans, retroactively:

- **User stories.** Any feature a person uses is framed as user stories ("As a <role>, I want <capability>, so that <benefit>"), each with a few concrete acceptance points. They go in one table, so a human can scan them easily: `| Story | As a | I want | So that | Acceptance criteria |`, one row per story, with a short numbered title and the criteria as short points separated by `<br>`. Purely internal features, such as infrastructure a user never touches directly, can say "not user-facing" instead.
- **Human checks.** A numbered, copy-pasteable list covering both the usual cases and the edge cases (see 1.3), so no one ever has to remember how to test a feature by hand. Use browser click paths for UI features and `curl` commands for HTTP endpoints. For other kinds, give the real command a person would run, such as a `pnpm saas` command, an Nx target or a `manage.py` command. A plan with nothing a human can usefully check says so and has no such section.

### 6.2 Choosing and citing reference repositories

When researching a plan, take inspiration from code written by humans, and prefer the most trustworthy sources:

- **Human-written code whose commit history is mostly from before 2024**, before the wave of AI-generated code (roughly 2024 to 2026), is a premium source of knowledge.
- **Trust signals** such as forks, stars, a long commit history and several real contributors raise a repository's value as a reference.
- **Repositories that lean toward software structure and engineering principles** (clear layering, tests, explicit design decisions) are preferred over ones that put speed, convenience, feature count or MVP shortcuts first.

When an external repository inspired a design decision, write it into the plan document next to the decision it informed, as a plain URL, so the rationale stays discoverable without chat history.

**Third-party API behaviour is cited, never assumed.** When a plan relies on how an external service behaves (a payment provider, an email provider, a cloud API), the AI agent reads that service's official documentation first. It puts an absolute, deep link to the exact section next to each fact the plan relies on, as section 1 of the PayFast plan does. Anything the docs don't state is marked as such and becomes a sandbox or live check in the plan, never a guess written as fact.

### 6.3 Keep the dev flow bindings in sync

`CLAUDE.md`'s "Dev flow bindings" table records this repository's concrete values: branch, CI, verification commands, commit convention, board and so on. When one of those things changes (a new Nx target, a renamed branch, a new plans folder), update its row in the same change, and update any rule in this document that quotes it. Rows are matched by label, so change the value, not the label. A binding that no longer matches reality misleads every future session.

### 6.4 Wiki code blocks need a source link

In the documentation site (`packages/internal/docs/docs/`), every code block quoted from the codebase must be immediately preceded by a real markdown link to the exact source file it came from. A path comment inside the fence doesn't count.

The same basics apply to every document under `docs/superpowers/` (plans, specs, walkthroughs):

- **Every file or folder the document references is a clickable link** to it, written relative to the document (for example `[`apps/payfast/services.py`](../../../packages/backend/apps/payfast/services.py)`), so the reader never has to find a file by hand. Check that every link resolves before handing the document over.
- **Code goes in fenced code blocks** with a language tag: commands to run, settings lines, and excerpts quoted from the codebase, copied exactly from the source. Names of functions, classes, settings and fields mentioned in a sentence stay as inline code.

### 6.5 Never leak the private downstream fork

This repository is public and open source for now, and is expected to become private at some point. Until then everything in it, including its git history, is treated as public, and anything pushed while it was public stays public. A private downstream fork exists for a real business. That business's name, its industry and any domain-specific terms from it must never appear anywhere in this repository: code, comments, docs, plans, commit messages or PR descriptions. This applies even when the human maintainer has explained that domain in conversation for context. The repository also must never contain secrets: real merchant IDs, keys, passphrases or webhook secrets go in untracked `.env` files or deployment secrets. Only placeholders, or the public sandbox credentials a provider documents, go in `.env.shared` and plans. Illustrative examples stay generic (a CRUD demo item, a donation, a generic SaaS plan).

---

## 7. Communicating with the human maintainer

The human maintainer usually works with AI agents in a terminal, where markdown renders only partially. Whatever the tool, write for that.

- **Write plain, absolute URLs** (`https://github.com/owner/repo`), never markdown `[label](url)` links. The terminal hides the URL behind the label, so the human maintainer can't click or verify it.
- **Avoid wide markdown tables.** Tables with many columns render unreadably in the terminal. Present comparisons as a per-item list: a heading line per item, then short "label: value" facts.

---

## 8. Conversation history and recall

An AI agent keeps no memory between sessions of its own. Sessions end, crash or get resumed, and context is lost each time. These rules keep that loss from costing the human maintainer work.

- **Know where your tool keeps its history.** Most AI coding tools save session transcripts or chat history to local files or to a history store the tool can read. The AI agent is responsible for knowing where its own tool keeps this, and how to read it with ordinary tools. It never claims that past sessions are impossible to retrieve without first checking.
- **Retrieve past messages immediately when asked.** When the human maintainer asks for messages from a previous session, for example after a crash or when resuming, the AI agent finds that session's history and retrieves the messages straight away. The previous session is usually the most recent one other than the current session. This is the standing exception to rule 1.1: the AI agent runs this retrieval itself.
- **"The exact text" means verbatim.** When asked to recall the exact text of an earlier message, fetch it word for word from the stored history, with the simplest single command or tool call that works. Never paraphrase, re-summarize or reconstruct it from memory, even if the message is still in view, because a paraphrase silently changes details the human maintainer relies on.
- **Summaries are not transcripts.** When a tool compresses or summarizes earlier context to make room, or a session is resumed from a summary, anything that needs exact detail (a decision, an error message, the wording of a rule) is checked against the stored history, the plan files in `docs/superpowers/plans/`, or this document before it is relied on.
- **Durable knowledge goes into the repository.** Plans, decisions and rules that must survive a session are written to `docs/superpowers/plans/` (see 6.1) and to this document, never kept only in the AI agent's context or private notes.

**Example, one tool's layout:** Claude Code stores each session as a JSONL file under `~/.claude/projects/<project-slug>/<session-id>.jsonl`, and a single command such as `jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="text") | .text' <file>.jsonl` extracts its assistant messages. Other tools use different locations and formats; the rules above apply regardless.
