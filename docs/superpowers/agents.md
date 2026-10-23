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

---

> ### ⚠️ CRITICAL: WHERE THE HOW-TO GUIDES LIVE
>
> **The comprehensive development how-to guides for this codebase are at
> [`packages/internal/docs/docs/`](../../packages/internal/docs/docs/).**
>
> **READ THESE BEFORE writing any code.** They document the established patterns
> for GraphQL (queries, mutations, schema updates, codegen, fragments, error
> conventions), backend patterns (Django models, DRF serializers, testing), and
> frontend patterns (components, forms, routing, Storybook). Ignoring them leads
> to wasted time debugging issues that the guides already solve.
>
> **AGENT DIRECTIVE:** If you are unsure of what commands to run, or what architecture
> is implemented, YOU MUST CHECK THE GUIDES FIRST. Always read the guides to
> understand the scaffolding and established patterns before starting a new feature
> or fixing a major bug.
>
> Key guides every AI agent must know:
>
> - [`packages/internal/docs/docs/working-with-sb/graphql/`](../../packages/internal/docs/docs/working-with-sb/graphql/) — **GraphQL data flow, schema updates, codegen commands**
> - [`packages/internal/docs/docs/working-with-sb/graphql/backend/adding-new-mutation.mdx`](../../packages/internal/docs/docs/working-with-sb/graphql/backend/adding-new-mutation.mdx) — **How to add mutations (model, serializer, schema, config/schema.py)**
> - [`packages/internal/docs/docs/working-with-sb/graphql/web-app/update-schema.mdx`](../../packages/internal/docs/docs/working-with-sb/graphql/web-app/update-schema.mdx) — **How to regenerate TypeScript types after backend changes**
> - [`packages/internal/docs/docs/working-with-sb/guides/backend/backend-model.mdx`](../../packages/internal/docs/docs/working-with-sb/guides/backend/backend-model.mdx) — **Django model creation patterns**

---

## Who is who

This document refers to three distinct parties. They are never interchangeable.

- **The human maintainer** is the person who owns this repository and is in charge of it. They decide its composition (what gets built, and in what order), orchestrate the work (which step comes next, when a RED or GREEN is confirmed, when something is committed and merged), and make the architecture and design calls. They are accountable for everything that lands in the codebase. They run every command, approve every change, and are the only party who can grant an exception to any rule below.
- **The AI agent** is whichever AI coding assistant is pair-programming with the human maintainer in a given session, whatever the tool, model or vendor. Every rule here applies to any AI agent equally. It proposes designs, writes tests and code within these rules, explains what it writes, and hands commands to the human maintainer to run. It never decides on its own to relax a rule, and it keeps no memory between sessions except what's written down (this document, the plans in `docs/superpowers/plans/`, the specs in `docs/superpowers/specs/`, and its own saved notes).
- **The original author** is Apptension, the team behind the upstream SaaS Boilerplate this repository was forked from (https://github.com/apptension/saas-boilerplate). They are not a participant in these sessions. "The original author's code" means everything that came from upstream, including what later `upstream/master` merges bring in, as opposed to what the human maintainer and the AI agent added. Section 3 explains why that code is handled with extra care.

---

## 1. Commands and execution

### 1.1 The human maintainer runs every command

The human maintainer runs every terminal command (shell, git, docker, pnpm, nx, uv, pytest, and so on) unless they explicitly say otherwise for a specific command. The AI agent does not run commands itself. It hands over the exact command to run, with a short explanation of what that command does, so the human maintainer understands it before running it. The explanation covers the syntax too, not only the overall effect: every flag and option (`--skip-nx-cache`, `-T`, `-e`), and every shell operator (`&&`, `;`, `|`, `$( )`, `2>&1`) the command uses. It is given every time, even for a command explained earlier in the session. The human maintainer's words: "always explain what a command does including syntax and flags".

- **Every command, or block of commands, starts with a Purpose line** (set by the human maintainer on 2026-10-14): "**Purpose:** …", saying what running it achieves and why it's needed now, in terms of the task (for example "the running backend still has the old code, so this rebuilds it"), before any flag is explained. It also says where to run it when that matters, such as "in a second terminal, leave `pnpm saas up` running in the first".
- **How a command is handed over.** The explanation comes first, then the command alone between a `COPY FROM HERE ▼` line and a `COPY TO HERE ▲` line, then what to expect. The human maintainer's terminal doesn't render code fences, so the markers are what separates the command from the comments. Inside a command, avoid two `*` or two `__` (the terminal reads them as markdown emphasis and drops them).
- **Several commands come as numbered blocks, one block per thing being checked** (set by the human maintainer on 2026-10-14). Each block tests one thing, such as the linter and type-check, the backend tests or the frontend tests, and sits between separator lines with a title saying what it checks (for example "BLOCK 2: products page tests"). A test block holds both forms of its command: the verbose form first, then the summary form, each labelled, with a note that either one runs the same tests. Each command in a block keeps its own explanation, COPY markers and expected result. Copy this layout exactly, rather than reinventing it, including the full explanation of every part of each command:

  ```text
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BLOCK 1: linter and type-check for webapp-shopify  (not tests, one form only)

  Purpose: the tests passed, but Jest doesn't check types or code style; these two checks catch a type
  mistake or a lint problem in the new code before it's committed, as CI would.

  - pnpm nx run webapp-shopify:lint: runs the lint target (ESLint, the code style and likely-mistake
    checker) of the webapp-shopify project, through Nx.
  - pnpm nx run webapp-shopify:type-check: runs the TypeScript compiler over the project to check
    types, without building anything. Jest doesn't check types, so only this catches a type mistake.
  - --skip-nx-cache: really runs the check, instead of Nx replaying a stored result from an earlier run.
  - > logs/webapp-shopify-lint.log: sends the normal output into that log file instead of the screen.
  - 2>&1: sends the error output to the same place as the normal output, so errors land in the log too.
  - ; : runs the next command whatever the result of the one before.
  - echo "webapp-shopify lint exit code: $?": prints a line with the exit code of the command just
    before. $? is that exit code: 0 means it passed, anything else means it failed.

  COPY FROM HERE ▼

  pnpm nx run webapp-shopify:lint --skip-nx-cache > logs/webapp-shopify-lint.log 2>&1; echo "webapp-shopify lint exit code: $?"
  pnpm nx run webapp-shopify:type-check --skip-nx-cache > logs/webapp-shopify-type-check.log 2>&1; echo "webapp-shopify type-check exit code: $?"

  COPY TO HERE ▲

  Expect: both exit code 0.

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BLOCK 2: products page tests  (either form runs the same tests)

  Purpose: confirm the GREEN: every products page test passes, including the ones written for this step.

  Verbose form, every test listed:
  - mkdir -p logs: makes the logs folder; -p means no error if it already exists.
  - pnpm nx run webapp-shopify:test: runs the project's Jest tests through Nx.
  - --skip-nx-cache: really runs the tests, instead of Nx replaying a stored result.
  - -- : everything after it is passed to Jest; Nx drops Jest flags placed before it.
  - --watchAll=false: Jest runs once and exits, instead of waiting for file changes.
  - --maxWorkers=2: at most 2 Jest processes at once, to keep memory use down.
  - --testPathPattern=shopifyProducts: only test files whose path contains "shopifyProducts".
  - --verbose: Jest lists every test by name, with ✓ (passed) or ✕ (failed), under its file.
  - 2>&1: error output joins the normal output, so both are shown and saved.
  - | tee logs/shopify-products.log: the pipe | hands the output to tee, which prints it on the
    screen and writes the same text to the log file.
  - echo "exit code: ${PIPESTATUS[0]}": prints the exit code of the first command in the pipe (Jest);
    a plain $? would give tee's exit code, which is always 0.

  COPY FROM HERE ▼

  mkdir -p logs; pnpm nx run webapp-shopify:test --skip-nx-cache -- --watchAll=false --maxWorkers=2 --testPathPattern=shopifyProducts --verbose 2>&1 | tee logs/shopify-products.log; echo "exit code: ${PIPESTATUS[0]}"

  COPY TO HERE ▲

  Expect: every test ✓, exit code 0.

  Summary form, counts only:
  - p=webapp-shopify: stores the project name in a variable called p; later, $p is replaced by it.
  - pnpm nx run $p:test … --testPathPattern=shopifyProducts: the same test run as the verbose form,
    without --verbose, so Jest prints only per-file results and totals.
  - > logs/shopify-products.log 2>&1: all output, errors included, goes to the log only.
  - sed 's/\x1b[[0-9;]*m//g' logs/shopify-products.log: reads the log and removes the colour codes
    Jest writes into it; s/…//g means "replace every match with nothing".
  - | grep -E "(Test Suites|Tests):": keeps only the lines with Jest's totals; -E allows the (a|b)
    "either" pattern. This | runs in the human maintainer's own shell, not through Nx, so it's safe.
  - | sed "s/^/$p: /": puts "webapp-shopify: " at the start of each line; ^ means line start.

  COPY FROM HERE ▼

  mkdir -p logs; p=webapp-shopify; pnpm nx run $p:test --skip-nx-cache -- --watchAll=false --maxWorkers=2 --testPathPattern=shopifyProducts > logs/shopify-products.log 2>&1; sed 's/\x1b[[0-9;]*m//g' logs/shopify-products.log | grep -E "(Test Suites|Tests):" | sed "s/^/$p: /"

  COPY TO HERE ▲

  Expect: webapp-shopify: Tests: N passed, N total.
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ```

- **Every message carries every block still to run, in full** (set by the human maintainer on 2026-10-17). Never write "run BLOCK 3 from my last message": diffs and long output bury earlier messages. When a fix interrupts a sequence of blocks, repeat the remaining blocks in the same message, renumbered, each with its full explanation. The human maintainer's words: "I am not going to scroll all the way up in our chat through all the text and diffs".
  - **The full set, with what's done ticked off** (added on 2026-10-21). Every message that hands over commands lists the whole sequence, in order. A command whose output the human maintainer has already sent is marked ✅ with its result; every other command is written out in full. The human maintainer's words: "I dont want to scroll through your messages to find the commands and the order and any missing ones."
  - **Human checks run from the plan file** (section 1.3), so for those, each message carries the whole ordered checklist (setup steps and numbered checks), with ✅ on those reported, and the next check's commands in full.
- **An edit request and commands never share a message** (set by the human maintainer on 2026-10-21). A message either asks permission for an edit (section 1.5), or hands over commands or checks to run, never both. The human maintainer's words: "Never make requests for an edit and issue a command/check verification in the same message."
- **Readable beats short.** Write each command out on its own line rather than folding a few into a shell loop: two plain `pnpm nx run …:lint` and `pnpm nx run …:type-check` lines, not `for t in lint type-check; do … done`. The human maintainer copies and pastes the commands either way, so readability is what matters (set by the human maintainer on 2026-10-14). A loop is kept only where writing every command out would be long and repetitive, such as the 15 frontend projects or the 12 backend modules in the README's Testing section.
- **Command output goes to the repository's gitignored `logs/` folder** (`mkdir -p logs; … > logs/<name>.log 2>&1`), never to the repository root, the home folder or `/tmp`, so the human maintainer always knows where every log is.

- This holds whatever permission or autonomy setting the AI agent's tool is running under. An auto-approving mode, or earlier commands in the same session that ran without objection, is never authorization to keep running commands. Such settings change how much the AI agent can decide without asking; they do not change who runs commands.
- Read-only commands (`ls`, `grep`, `cat`, `find`) are not exempt. To inspect the codebase, the AI agent uses its tool's built-in file-reading and search features, not shell commands.
- **When the human maintainer does authorize a specific command** ("run the command", "just do it"), the AI agent runs it immediately, in that same turn, with no re-explaining, hedging or second confirmation.
- **Standing exception: fetching past conversation text.** When the human maintainer asks for messages from a previous session, or the exact text of an earlier message, the AI agent retrieves it itself straight away (see section 8).

### 1.2 Use the real entrypoint for verification

When giving manual verification steps, use the real top-level command a user or a deployment would run (a documented `pnpm saas` command, an Nx target), not a hand-built sequence of its internal sub-steps. Examples: `pnpm saas down` then `pnpm saas up`, not a hand-picked `docker compose up` of individual services; and `pnpm nx run backend:test`, not a bare `pytest`, because the Nx target also runs the formatter and the migrations check. Verification should exercise the whole real workflow, not an approximation that happens to reach the same state.

**Look the command up before writing one** (set by the human maintainer on 2026-10-15). Before handing over a command, check whether a documented one already does the job:

- [`packages/internal/docs/docs/api-reference/index.mdx`](../../packages/internal/docs/docs/api-reference/index.mdx) has the "Common Commands" quick reference.
- [`packages/internal/docs/docs/api-reference/backend/commands.mdx`](../../packages/internal/docs/docs/api-reference/backend/commands.mdx) lists every backend command.

For example, migrations are made with `pnpm saas backend makemigrations`, not a hand-built `docker compose run --rm backend python manage.py makemigrations`.

### 1.3 The verification ladder

- **RED step:** run the single test file.
  - Backend: `docker compose run --rm -T backend pytest <path> -v`. Tests run in the backend container against its Postgres, and `setup.cfg` loads `.test.env`.
    - **Check which database that is first.** [`config/settings.py`](../../packages/backend/config/settings.py) prefers `DATABASE_URL` over `DB_CONNECTION`, and `.test.env` doesn't override it. If `packages/backend/.env` sets `DATABASE_URL` to a remote database (for example a hosted Postgres also used by a deployment), the suite runs there instead of the local `db` container: very slowly, and it creates a `test_*` database on that server. Keep `DATABASE_URL` unset for local development, or add `-e DATABASE_URL=` to the `docker compose run` command.
    - **[`.test.env`](../../packages/backend/.test.env) must not contain comment lines.** [`run_tests.sh`](../../packages/backend/scripts/runtime/run_tests.sh) loads it with `env $(cat .test.env | xargs)`, which breaks on `#` lines, so `backend:test` fails at the migrations check. Explain a value in the plan or walkthrough instead.
  - Frontend: `pnpm nx run <project>:test --watchAll=false --testPathPattern=<path>`, e.g. project `webapp-finances`.

  A RED has to be seen as a running test failure. Lint and type-check stop before any test runs, so they can't show a RED.

- **GREEN step:** run the project's full Nx targets, not just the single file.
  - Backend: `pnpm nx run backend:test`. It runs `ruff check` (report-only), `black`, `manage.py makemigrations --check --dry-run`, then the whole pytest suite with coverage.
  - **When the full backend run is needed** (set by the human maintainer on 2026-10-16). It takes 10 to 15 minutes, so it runs only where it can catch something.
    - **Full run:** `pnpm nx run backend:test` when a step touches anything outside its own Django app (`config/`, `common/`, another app, `pyproject.toml`, the root `conftest.py`), and always before a commit.
    - **A step that touches only its own app's files** runs that app's tests (`docker compose run --rm -T -e DATABASE_URL= backend pytest apps/<app>`) plus `pnpm saas backend black`.
    - **If that step changed a model,** `pnpm saas backend makemigrations` must list only the app's expected migration, and a second run must say "No changes detected". That stands in for the full run's missing-migrations check.
  - Frontend: `pnpm nx run <project>:lint`, `pnpm nx run <project>:type-check` and `pnpm nx run <project>:test --watchAll=false`, for every Nx project touched.

  These are the same targets CI runs (`.github/workflows/backend.yml`, `.github/workflows/webapp.yml`). They catch a GREEN whose tests pass but that breaks a type, a lint rule, formatting or a missing migration.

- **Test commands come in two forms, summary and verbose, and both keep a log** (set by the human maintainer on 2026-10-12: the counts per module show the volume of tests at a glance, and the verbose form shows each test's name, file and result). The commands are in the README's Testing section; hand over both, in those formats, the verbose form first and the summary form second:
  - **Summary:** the run writes only to `logs/`, then the terminal shows the counts. Backend, one line per module: `apps/shopify: 88 tests | 88 passed, 45 warnings in 33.37s` (the total from pytest's `collected N items` line, the rest from its last line). Frontend, two lines per project: `webapp-shopify: Test Suites: 2 passed, 2 total` and `webapp-shopify: Tests: 13 passed, 13 total`.
  - **Verbose:** the run prints one line per test with its file and pass or fail result. Backend pytest already does (`-v` is in `addopts` in [`setup.cfg`](../../packages/backend/setup.cfg)); for a bare `pytest`, add `-v`. Frontend Jest needs `--verbose`, which lists each test under its file's `PASS` or `FAIL` line. Through Nx, every Jest flag goes after a bare `--` and only `--skip-nx-cache` before it (`pnpm nx run <project>:test --skip-nx-cache -- --watchAll=false --maxWorkers=2 --verbose`): Nx has a `--verbose` flag of its own, so Jest's must follow `--`, and once `--` is there Nx passes on only what follows it, silently dropping Jest flags placed before it (found 2026-10-14; the log's `> nx run ...` line shows what was passed on). A Jest filter passed through Nx can't contain `|`, even in quotes: Nx re-runs the command in a new shell without the quotes, so `|` becomes a pipe. Run one command per pattern instead;
    It streams to the terminal and to the gitignored `logs/` folder at once, with `2>&1 | tee logs/<name>.log`, then prints the test command's own exit code with `echo "<name> exit code: ${PIPESTATUS[0]}"` (a plain `$?` would give `tee`'s exit code, always 0).

  Lint, type-check and other non-test commands keep writing only to their log, with `> logs/<name>.log 2>&1`. The workers' `pnpm nx run workers:test` is the one exception: its upstream script runs `pytest` without `-v` and has only 2 tests, so it shows the summary line only.

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
  - for an HTTP endpoint (a webhook such as the PayFast ITN, the REST API, or the GraphQL API at `/api/graphql/`), the exact, human-readable `curl` command, with a login step and one cookie file per user where needed

  The checks live in the plan, not only in chat, so they survive between sessions and can be re-run at any time. Aim for 5 to 20 checks per step. Seeded rows the checks act on get fixed ids, so the commands can be pasted as written.

- **Human checks have their own top-level "Human checks" section in the plan, with a clear start and end** (set by the human maintainer on 2026-10-16).
  - It opens with a line saying the human checks start there, and closes with "Human checks end here.", so nothing a human runs is mixed into planning text.
  - Inside, in this order:
    - Setup
    - Seeded data
    - Who can do what
    - the checks, grouped by feature and numbered
  - Each check's title states its expected result, for example "A bad signature: 403, and nothing stored". Each carries its **Why**, **Acts on**, commands and **Expect** lines.
  - A list of checks not yet written out stays elsewhere, under a heading that says it's planned, not runnable.
  - The model is the "Human checks" section of `docs/plans/10-profile-editing.md` in the sister repository `fastapi-clean-example`.

- **Human checks are exact and unambiguous: no placeholders, ever.** The human maintainer's words: "No placeholder values please, it makes life hard for no reason. No ambiguity."
  - Every login is written out as its own command or click path, with the real seeded email and password, right before that user's first step. Never "log in as X first" without the command.
  - No `<id>`, `<your store>` or similar to fill in. A value only known at run time (such as a new row's id) is captured into a shell variable by the command that creates it, then reused as `$VARIABLE`. A value that is genuinely the human maintainer's own (their dev store's domain, their ngrok address) is named once at the top of the checks, with where to find it.
  - No "re-run check N" or "run it again": repeat the command or click path in full where it's needed, so the checks read top to bottom in the order they're run.
- **Every human check explains what it's testing and why.** A short title like "A Member can't connect a store" isn't enough. Each check gets a **Why** line: the rule being tested (for example "connecting needs `shopify.manage`"), why the rule exists, and why this result rather than a similar one (for example "Store not found" rather than a permission error, so nobody can learn another organization's stores). A feature with roles or permissions also gets a short "who can do what" reference before its checks. The human maintainer's words: "The more I know what I am testing against, the easier."
- **Prove every assumption with a command before relying on it.** If a check depends on a starting state ("this user is a Member", "this store is uninstalled"), it first shows that state (a read-only `curl`, a Django admin page, or a `manage.py shell` one-liner), before the step under test. The same goes for the result: a check that changes something ends by showing the change, rather than trusting a status code or a toast.
  - Each check proves its own starting state, right before its step under test, even if an earlier check already showed it. Never write "check N proved…".
  - Each check logs in every user it acts as, at its own start. Never rely on "logged in at check N": a session can expire while a human reads the checks.
  - When behaviour hinges on a distinction (for example "not found" versus "no permission"), give it its own self-contained check showing the cases side by side, with only the variable that matters changed.
  - Name every id. Wherever a command uses an id, an **Acts on:** line says what it is (the organization's name, whose membership, which store). A bare id tells a human nothing.
- **Everything a check prints is human-readable.** JSON always goes through `python3 -m json.tool`, including on a command that also shows its status code: `curl -s -w '%{stderr}%{http_code}\n' … | python3 -m json.tool` prints the code on its own line, then the JSON one field per line. Only a response with no body uses `curl -s -o /dev/null -w '%{http_code}\n'`. Never throw away a body the check's **Expect** line asks the reader to look at.
- **State is set and shown with terminal commands; the browser is only for what needs eyes on a page** (set by the human maintainer on 2026-10-15). Creating test data, reading an id, switching context or building an address is a command (a `curl` to the API, a `manage.py` command), with any value it finds kept in a shell variable and printed, never "note the id in the address bar" or "click through to create it". For example, `echo "http://localhost:3000/en/$ORG_A_ID/"` prints the page a check should open. The browser part of a check is limited to looking at what the page shows.
- **Every `curl` in a human check is readable at a glance** (set by the human maintainer on 2026-10-15). One request per code block; each block is introduced by a short sentence saying who acts and what the request is ("Log in as …", "**Prove** …", "Then, as …, ask for …"), and followed by its **Expect** line. Inside the block, the URL stays on the first line and each further option (`-H`, `-d`, `-b`, `-c`) goes on its own line, joined with a trailing ` \`. A JSON body that needs shell values is built with `jq -n --arg name "$VALUE" '{ … }'`, never with escaped quotes (`\"`) or a `python3 -c` one-liner, and a GraphQL request sends values as GraphQL variables. When two requests differ in one value, write both out in full and say which value changed. The model to copy is the human checks of `docs/plans/10-profile-editing.md` in the sister repository `fastapi-clean-example`. Long human checks are run from the plan file, not pasted into chat: a chat that renders markdown drops a line-ending backslash.
- **Show whole objects, never a few picked fields.** A command that prints only selected fields hides the rest, and a wrong value in a hidden field goes unnoticed. To narrow a list, filter the rows but print each one whole, as pretty JSON. A count is fine as an extra line next to the whole objects, never instead of them. The human maintainer's words: "Its always better to see the entire object."

### 1.4 Git follows the documented protocol exactly

When committing, pushing or opening a PR, follow the repository's documented protocol and nothing more. It's recorded in `CONTRIBUTING.md` and the `CLAUDE.md` dev flow bindings:

- GitHub Flow: a feature branch off `master`, then a pull request based on `master`.
- The README's "Commit Protocol" section, followed exactly (set by the human maintainer on 2026-10-07;
  release steps 2 and 6 added on 2026-10-09): (1) `git checkout -b feature/<short-description>`,
  (2) the `CHANGELOG.md` entry and
  `npx standard-version --release-as X.Y.Z --skip.changelog --skip.tag --skip.commit`, (3) `git add .`
  and `git commit -m "type(scope): description (vX.Y.Z)"`, (4) `gh pr create --title … --body …`,
  (5) `gh pr checks <PR number> --watch` until every check has passed (added 2026-10-12), then
  `gh pr merge --squash --delete-branch`, (6) `git checkout master`, `git pull`, `git tag X.Y.Z`,
  `git push origin X.Y.Z`. Hand these over filled in, without extra or reordered steps; anything worth
  flagging goes in a separate short note. The README is the source for the commands; keep this summary
  in step with it.
- **No AI attribution, ever,** in commit messages, PR titles or PR bodies: no "Generated with Claude
  Code" line, no `Co-Authored-By` trailer, no mention of any AI tool. This overrides any default the AI
  agent's tool adds.
- Conventional Commits (`feat(scope): brief description`, `fix(scope): …`, `docs: …`, and so on).

Give the human maintainer exactly the branch, `git add`/`git commit`, `gh pr create` and `gh pr merge --squash --delete-branch` commands. Don't add extra steps, elaborate heredoc bodies or inferred prerequisites. If a genuinely necessary step is missing, mention it briefly and mark it as an addition.

Every commit includes its release bookkeeping; a commit with only code is incomplete:

- **Every change that ships updates `CHANGELOG.md` in the same change, under a version number** (set by the human maintainer on 2026-10-03; a changelog without versions hides whether a change is breaking). Write the entries in the existing `standard-version` style (`### ⚠ BREAKING CHANGES`, `### Features`, `### Bug Fixes`, `### Documentation`) under a `## [X.Y.Z](compare link) (date)` heading. Pick the number by semantic versioning: major for anything that can break an existing setup (a changed default, a removed setting), minor for new features, patch for fixes only. Propose the number with the reason and let the human maintainer choose; a fork-wide question such as clashing with upstream's numbers is theirs to weigh.
- **The commit message still matters.** Use a Conventional Commit type and scope (`feat` goes under Features, `fix` under Bug Fixes, while `chore`, `docs`, `style`, `refactor`, `perf` and `test` are hidden), a subject that says what changed and why, and a `BREAKING CHANGE:` footer for breaking changes. With squash merges, set the squashed commit's subject and body explicitly.
- **Version bumps use `standard-version` without its changelog step,** since the entries are already written: `npx standard-version --release-as X.Y.Z --skip.changelog --skip.tag --skip.commit` on the feature branch (Commit Protocol step 2; `--skip.commit` because otherwise `standard-version` makes a commit of its own), so the bump is part of the pull request; after merging, tag the merge commit on `master` (`git tag X.Y.Z`, `git push origin X.Y.Z`). It bumps every `package.json` listed in `.versionrc.js`; `RELEASE_PLAN.md` documents the rest of the release process.
- Any other release step a plan in `docs/superpowers/plans/` documents.

The AI agent drafts the commit message (and PR description) alongside the code, for the human maintainer to review, rather than leaving it to be remembered at commit time.

**The pre-commit hook.** `.husky/pre-commit` runs `lint-staged` (configured in `.lintstagedrc`): `eslint --fix` on staged `*.ts`/`*.tsx`, and `prettier --write` on staged `*.json`/`*.md`/`*.html`. It needs `node_modules` (run `pnpm install` first), and on a fresh clone it builds the Nx graph once. Two consequences:

- The hook may rewrite staged files. Review what it changed before pushing; don't blindly re-stage.
- The hook doesn't check Python. Python formatting (`black`) and linting (`ruff`) only run inside `pnpm nx run backend:test`, so run that target before committing any backend change. Don't rely on CI to catch it.

Never bypass the repository's safeguards to get a commit or push through: no `--no-verify` to skip pre-commit hooks, no setting `CI=1` locally to make the hook exit early, no `--force` pushes, no skipping or silencing a failing check. When a hook or check fails, the failure is information; fix what it found. See 4.4.

### 1.5 Every file change is asked for first, and shown as a diff

Whenever the AI agent wants to create, edit or update a file, it asks the human maintainer's permission first, unless the human maintainer has said it may work autonomously. The human maintainer's words: "When ever you want to edit/update/create a file, always ask me for permission unless I give you permission to work autonomously."

- **Every change is made so the human maintainer sees the diff:** with the AI agent's tool's own file-editing feature, which shows the exact lines removed and added. Never by running code that rewrites files (a `python3` script, `sed -i`, a heredoc redirected into a file, and so on), which hides the change (set by the human maintainer on 2026-10-14). The human maintainer's words: "If you need to edit files, dont edit files using code, rather edit the files by showing the diff and asking for approval".
- **Before asking, the AI agent says what it will change and why** (see 5.2), so the permission is an informed one.
- **Permission is asked per TDD step, not per edit:** once for a RED (the tests it adds and what each one proves) and once for a GREEN (the code change that makes them pass). With a yes, the AI agent makes all of that step's edits straight away, each shown as a diff, without asking again file by file. The same goes for a non-code step, such as a docs or plan update. The human maintainer's words: "Just ask permission for a red or a green edit/creation, and explain what change you propose for a red or green. Then jump straight to the red or green change where I see the diff."
- A request from the human maintainer that names the change ("update agents.md with…", "fix that test") is that permission, for that change only.

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

### 2.5 Every test file says what kind of test it is

Set by the human maintainer on 2026-10-17. Upstream keeps every app's tests in one flat `tests/` folder, with no unit or integration folders and no pytest markers, and CI runs them all at once. This fork keeps that layout (section 3.1), so the boundary between kinds of test is written down instead.

- **Each backend test file's module docstring names its kind,** one of four (set by the human maintainer on 2026-10-17):
  - **sanity:** the app is wired up and configured correctly. The settings read their environment variables (`test_settings.py`), and the Django system checks catch a broken configuration (`test_checks.py`).
  - **unit:** one module's logic on its own, with no database and no network. An API client counts, with the provider's HTTP faked. Such a file still carries `pytestmark = pytest.mark.django_db`, only because the root `conftest.py`'s autouse fixtures need the database.
  - **integration:** the code working with a real collaborator. That's either the test database, for a model, service, command or Celery task, or a request through a route with Django's test client: a view, a webhook, the GraphQL API or the admin.
  - **smoke:** a whole user journey through the real stack, across several entrypoints, such as PayFast's `test_smoke.py`.
- **The docstring says why the file is that kind, and what's faked,** for example `Kind of test: integration (agents.md section 2.5). Why: the client saves the wa_id Meta returns on the contact, in the test database; Meta's HTTP is mocked.` No test reaches a real third-party service. A file that mixes kinds is labelled by its main kind, and the Why line names the exception.
- **Support code gets no such line:** `conftest.py`, `factories.py`, payload builders and other helpers aren't tests (section 2.1).
- **Each plan's Verification section has a short "Kinds of test" list,** grouping the plan's test files by kind, so a reader sees at a glance how much is unit-tested logic and how much is integration through the database or a route.

### 2.6 No `transaction=True` backend tests

Found on 2026-10-17. A test marked `@pytest.mark.django_db(transaction=True)` empties every table when it ends, including the rows data migrations created, such as the permissions. `setup.cfg` runs pytest with `--reuse-db`, so the emptied database carries into the next local run, and unrelated tests that read those rows then fail there, while CI, which builds a fresh database, still passes. `serialized_rollback=True` doesn't help: it restores the data before such a test, not after it.

- **Keep every test in the normal test transaction.** Upstream has no `transaction=True` tests either.
- **When a test seems to need one, change what it waits on.** Two examples from the WhatsApp send queue:
  - A lock that a second connection holds: use a Postgres advisory lock, which needs no committed rows.
  - A Celery task run with `apply()`, whose `config/celery.py` signals close the connection: disconnect those receivers in a test fixture.
- **If the local database is already emptied,** rebuild it once: `docker compose run --rm -T -e DATABASE_URL= backend pytest --create-db apps/<app>`.

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

The same applies to tests the original author skipped (`it.skip`, `describe.skip`, `pytest.mark.skip`): they stay skipped in this fork, even when no reason is written down (set by the human maintainer on 2026-10-09). The upstream team has about 30 contributors and this fork has two people and an AI agent, so upstream's reasons are the better bet. Record such skips as known gaps in the relevant plan rather than un-skipping them.

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
- **A new Django app gets its empty `migrations/__init__.py` in the same GREEN as its first model** (set by the human maintainer on 2026-10-15).
  - **Why it's needed:** without an app name, `makemigrations` only looks at apps that already have a `migrations` package. `pnpm saas backend makemigrations` runs it without one, so a new app with no package is skipped silently, with "No changes detected".
  - **Why nothing else catches it:**
    - The `makemigrations --check` step in `backend:test` skips the app the same way.
    - The test database still gets the app's tables, because Django creates tables directly for an app without migrations.
    - So every check passes while a real deployment would have no tables at all.
  - **Then confirm:** run `pnpm saas backend makemigrations`, and check that the new app appears in its output.
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

### 4.5a Use cases are the north star of every design

Set by the human maintainer on 2026-10-22 ("Let this be our north star for iterative design"), after an AI agent drifted into a design no use case needed: an operator-owned WhatsApp "platform number", copied from a reference app, with a new party added quietly to the plan's "Who's who" after the human maintainer's first review. The human maintainer's words: "I expect both us to think smarter about use cases that drive our design", and "I am not a machine and I can't read large amounts of documentation again and again".

- **Every design proposal starts with one line naming the use case it serves,** and how it moves the feature closer to its goal. For the WhatsApp work, the goal is: a Shopify business signs up to this SaaS, connects its own store's WhatsApp number, and talks with its customers there. If that line can't be written, say so instead of proposing.
- **A new party, role or kind of thing is raised in chat, in plain words, before it goes in any document,** and never added quietly to a plan.
- **Decisions are short and taken one at a time,** not long option lists the human maintainer has to cross-check against the plan.

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

**Link the provider's documentation wherever code talks to a third-party API** (set by the human maintainer on 2026-10-15).

- Application code that builds a request to an external service, or reads a payload from one, carries a comment with the absolute URL of the official documentation page for that endpoint, field or rule. External services include Meta's WhatsApp Cloud API, Shopify, PayFast and OpenAI.
- The same goes for tests that build such a payload.
- Debugging an integration usually means reading the provider's documentation, and the link puts it one click from the code that depends on it. It's the code-side twin of section 6.2's rule for plans.

### 5.2 Explain code before showing it

Whenever the AI agent proposes code for review, it explains what the code does in three places: in the code's own design and structure, in code comments, and in the chat message. The chat explanation comes _before_ the diff, so the human maintainer never has to reverse-engineer intent from a wall of changed lines.

### 5.3 Exact-pin every new dependency

Every dependency the human maintainer and the AI agent add is pinned exactly.

- **Python:** `==` in `packages/backend/pyproject.toml`, runtime and dev groups alike. After `uv add`, immediately tighten the constraint to the exact version resolved in `uv.lock`.
- **JavaScript:** an exact version with no `^` or `~` in the relevant `package.json`, added with `pnpm add --save-exact --filter <project>`.

Upstream's existing constraints are mixed (`==`, `~=`, `>=`, `^`). Leave them as they are (section 3), because re-pinning them would conflict with every upstream merge. Check this whenever the dependency lists are touched.

### 5.3a Call providers' HTTP APIs directly, not through their SDKs

The maintainer's rule, 2026-10-20. In code the human maintainer and the AI agent write (not upstream's), a third-party API such as OpenAI's or Meta's is called with plain HTTP requests (`requests`), through one small client class of our own. Examples are `apps/whatsapp/client.py` for Meta and `apps/whatsapp/agent/provider.py` for OpenAI. The provider's SDK is neither added nor used.

- **Why:** an SDK is one more dependency with its own bugs, breaking changes and deprecations. OpenAI's Assistants API was retired, and patching the `openai` SDK's client class in upstream's tests broke every later test that built one. A class of our own keeps the exact request visible in one place and testable with `requests.post` patched, and it can be changed without waiting for anyone's release.
- **How:** set an explicit timeout on every request. Turn the provider's failures into one exception type of our own, and never put a secret, or text the provider may have echoed back from the request, in its message. Link each request to the provider's own reference page (section 5.1).
- **Upstream's existing SDK uses** stay as they are (section 3).

### 5.3b An enum is stored with exactly its member names

Set by the human maintainer on 2026-10-22. Every enum in code the human maintainer and the AI agent write is stored in the database with exactly its member names: `INTERNAL_COMMUNICATIONS = "INTERNAL_COMMUNICATIONS"`, never `"internal"` or another spelling. A setting that takes an enum's values takes those same names. The human maintainer's words: "Every enum in the application (for commits we pair programme on) should be mirrored in the database, no ambiguity, no deviations, no nonsense", because "Databases are often checked by humans who have to know what fields mean semantically".

- **A provider's own codes** (Meta's lowercase `sent`, PayFast's frequency `3`) are translated to the enum's names where they come in, and back where they go out, never stored as they arrive.
- **Upstream's enums** stay as they are (section 3).

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

Whenever a plan records a test result (a RED, a GREEN, or a run of several suites), it gives the exact command that produced it, copied as it was run, next to the result (set by the human maintainer on 2026-10-07). A result without its command can't be re-run or checked.

Whenever an AI agent creates a plan, it always externalizes it as a file in `docs/superpowers/plans/` so it survives across sessions. The plan file in this codebase is the single source of truth, not the ephemeral plan in the AI agent's own tools (such as a plan-mode draft or a to-do list), which disappears when the session ends. Read from the file and write updates to it, never to a draft held elsewhere or only in the conversation. Good test coverage is a stated goal of every plan, not an afterthought.

Two further sections belong in every plan where they apply, including older plans, retroactively:

- **User stories.** Any feature a person uses is framed as user stories ("As a <role>, I want <capability>, so that <benefit>"), each with a few concrete acceptance points. They go in one table, so a human can scan them easily: `| Story | As a | I want | So that | Acceptance criteria |`, one row per story, with a short numbered title and the criteria as short points separated by `<br>`. Purely internal features, such as infrastructure a user never touches directly, can say "not user-facing" instead. The rest of this list was set by the human maintainer on 2026-10-15, taken from the plans of the sister repository `fastapi-clean-example`:
  - **Where they go:** right after the plan's Goal, before any design or Proposed Changes, so a reader meets what the feature is for before how it's built.
  - **Who's who first, when a feature has more than one kind of user.** A short list names each kind and how the system knows them (for example "SaaS user: has an account and memberships" versus "shopper: known only by a WhatsApp number, never a member"). The "As a" column then uses exactly those names.
  - **Each title names the steps that deliver it,** for example "4. Create an organization in chat (Steps 5, 6)", so a reader can go from a need to the code that meets it.
  - **Cited as "user story N",** never with an ID scheme such as `US-1`. A story in another plan is cited with that plan's path. Numbers never change once given, because other documents cite them; a capability added later gets the next number.
  - **A promise not to do something is a story too.** A boundary a user relies on, such as "a shopper never sees another store's products", gets its own row. Smaller edge cases go in the acceptance criteria of the story they belong to.
  - **Out-of-scope items are not stories.** They go in a "Deliberately out of scope" list with the reason, so a deferred capability isn't mistaken for a promised one.
  - **Every story is covered by at least one human check,** whose **Why** line names it ("(user story 3)"), so the checks prove the promises the stories make.
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
- **Never split an inline code span across two lines.** Put a long span on its own line instead. The pre-commit hook runs `prettier --write` on staged markdown, and a split span can make it merge a list into a paragraph or turn `__tests__` into bold text. Run `npx prettier --check <file>` after editing any markdown file.

### 6.5 Never leak the private downstream fork

This repository is public and open source for now, and is expected to become private at some point. Until then everything in it, including its git history, is treated as public, and anything pushed while it was public stays public. A private downstream fork exists for a real business. That business's name, its industry and any domain-specific terms from it must never appear anywhere in this repository: code, comments, docs, plans, commit messages or PR descriptions. This applies even when the human maintainer has explained that domain in conversation for context. The repository also must never contain secrets: real merchant IDs, keys, passphrases or webhook secrets go in untracked `.env` files or deployment secrets. Only placeholders, or the public sandbox credentials a provider documents, go in `.env.shared` and plans. Illustrative examples stay generic (a CRUD demo item, a donation, a generic SaaS plan).

The same goes for the human maintainer's own details (set by the human maintainer on 2026-10-15): their email, account names, organization names, dev store domain, tunnel address, app ids and ids from their local database never go into a tracked file, a plan, a commit or a PR. Human checks get such values at run time instead (for example with `read` into shell variables, see 1.3), and examples use made-up values.

---

## 7. Communicating with the human maintainer

The human maintainer usually works with AI agents in a terminal, where markdown renders only partially. Whatever the tool, write for that.

- **Write plain, absolute URLs** (`https://github.com/owner/repo`), never markdown `[label](url)` links. The terminal hides the URL behind the label, so the human maintainer can't click or verify it.
- **Avoid wide markdown tables.** Tables with many columns render unreadably in the terminal. Present comparisons as a per-item list: a heading line per item, then short "label: value" facts.
- **Never use the section sign "§".** Write "section 10" (or "Section 10" at the start of a sentence). This applies everywhere: chat, plans, specs, walkthroughs and code comments.
- **Explain simply.** The human maintainer is an experienced developer, but some tools in this stack are new to them (for example Nx, Celery, Redis or a payment provider's API). Say in plain words what a tool or step does before using its jargon, keep explanations short, and prefer one concrete example over a general description.

---

## 8. Conversation history and recall

An AI agent keeps no memory between sessions of its own. Sessions end, crash or get resumed, and context is lost each time. These rules keep that loss from costing the human maintainer work.

- **Know where your tool keeps its history.** Most AI coding tools save session transcripts or chat history to local files or to a history store the tool can read. The AI agent is responsible for knowing where its own tool keeps this, and how to read it with ordinary tools. It never claims that past sessions are impossible to retrieve without first checking.
- **Retrieve past messages immediately when asked.** When the human maintainer asks for messages from a previous session, for example after a crash or when resuming, the AI agent finds that session's history and retrieves the messages straight away. The previous session is usually the most recent one other than the current session. This is the standing exception to rule 1.1: the AI agent runs this retrieval itself.
- **"The exact text" means verbatim.** When asked to recall the exact text of an earlier message, fetch it word for word from the stored history, with the simplest single command or tool call that works. Never paraphrase, re-summarize or reconstruct it from memory, even if the message is still in view, because a paraphrase silently changes details the human maintainer relies on.
- **Summaries are not transcripts.** When a tool compresses or summarizes earlier context to make room, or a session is resumed from a summary, anything that needs exact detail (a decision, an error message, the wording of a rule) is checked against the stored history, the plan files in `docs/superpowers/plans/`, or this document before it is relied on.
- **Durable knowledge goes into the repository.** Plans, decisions and rules that must survive a session are written to `docs/superpowers/plans/` (see 6.1) and to this document, never kept only in the AI agent's context or private notes.

**Example, one tool's layout:** Claude Code stores each session as a JSONL file under `~/.claude/projects/<project-slug>/<session-id>.jsonl`, and a single command such as `jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="text") | .text' <file>.jsonl` extracts its assistant messages. Other tools use different locations and formats; the rules above apply regardless.
