# Production Readiness Roadmap

> **Roadmap, not an implementation plan.**
>
> A prioritized backlog of known gaps between this fork's current state and what a real deployment
> needs, written down so the list survives across sessions instead of living only in chat history. It
> stays generic, like the rest of the repository: no business domain, deployment target or private
> fork is assumed.
>
> Each open item is a candidate for its own plan in `docs/superpowers/plans/` (numbered steps, the test
> file before the production file in each step, a File Summary, a Verification Plan with human checks)
> once it's prioritized. Items found while working on a plan say where. Numbered `0-` so it sorts first.

---

## Checklist (summary)

**Already implemented**

- [x] PayFast payments beside Stripe, chosen by `PAYMENT_BACKEND` (6.0.0):
      `2026-09-30-payfast-payment-backend-plan.md`, walkthrough `../specs/2026-10-01-payfast-walkthrough.md`
- [x] Shopify app install, linking stores to organizations, webhooks and token refresh (6.1.0), with
      component tests and clearer errors (6.1.2): `2026-10-03-shopify-app-installation-plan.md`, steps 1
      to 10
- [x] A green test suite in CI, with a guard that every frontend library with tests is in CI's list
      (6.1.1): `2026-10-07-restore-green-test-suite-plan.md`
- [x] Shopify walkthrough with diagrams: `../specs/2026-10-12-shopify-walkthrough.md` (Shopify plan
      step 13)
- [x] Shopify products page, with cursor paging and a "products per page" picker (6.2.0): Shopify plan,
      step 11

**P0: fix before a real deployment**

- [ ] **Test runs report to the real Sentry project.** `packages/backend/.env` sets `SENTRY_DSN`, and
      the test container reads it, so every backend test run and failing management command sends
      events ("Sentry is attempting to send 1 pending events"). Tests and local commands should never
      reach Sentry: an empty `SENTRY_DSN` for tests (for example in `.test.env`), checked by a test.
      Found 2026-10-12, Shopify plan step 11.
- [ ] **The link page's "Store is already connected." becomes a generic message in production.** With
      `DEBUG` off, `SanitizeErrorsMiddleware` replaces any GraphQL error that isn't a safe type, so
      decision C (6.1.2) only works locally. Fix with the convention the products page uses:
      `GraphQlValidationError({"non_field_errors": [message]}, code=…)`, and read the code on the page.
      Found 2026-10-12, Shopify plan step 11, cycle 4.
- [x] **`packages/backend/apps/shopify/shopify.app.toml` held a personal tunnel address and the app's
      client id, and git tracked it** (committed in 6.1.0). Untracked and added to `.gitignore` in 6.2.0;
      the working copy stays on disk for the Shopify CLI. Found 2026-10-15, Shopify plan step 11.

**P1: visible to users, worth doing soon**

- [ ] **Prices on the Shopify products page are shown as Shopify sends them** (`USD 600.0`,
      `USD 10.0 – 100.0`). Format them as money with the browser's currency formatting
      (`Intl.NumberFormat`), padding to the currency's decimals without ever rounding. Its own RED/GREEN
      step in `webapp-shopify`. Found 2026-10-15, Shopify plan step 11, human check 17.
- [ ] **A personal organization can't be picked again in the sidebar's organization switcher.**
      Upstream has the "Personal account" entry commented out in `tenantSwitchSidebar.component.tsx`, so
      after switching to another organization the only way back to a personal one is its address.
      Upstream code (`agents.md` section 3.4): raise it, don't change it unasked. Found 2026-10-14,
      Shopify plan human check 21. Hit again on 2026-11-01, in the WhatsApp checks (the maintainer:
      "Very frustrating"). The way back without code: in the browser's developer tools, delete the
      `currentTenant` local-storage entry for http://localhost:3000, then open http://localhost:3000/en/.
      With no organization in the address and none stored, the app opens the personal one
      (`currentTenantProvider.utils.ts`).
- [ ] **The fork's tables mostly have plain integer ids, which people and AI agents confuse.** A
      WhatsApp contact or message shows as `2` in the admin, and an id like that can't be told from a
      quantity or another table's row. Only `WhatsAppAccount` and `MetaApp` use upstream's hashid field.
      Hashids alone aren't enough either: they encode the same integer the same way in every table, so
      on 2026-11-01 a Meta app and a WhatsApp number both showed as `7Dbgob4`. Options: A, hashids with
      a prefix per model (the hashid field's `prefix=`), near no-op migrations, recommended; B, UUIDs, a
      much bigger migration. Raised by the maintainer, 2026-11-01, WhatsApp plan Step 2.9 human checks.
- [ ] **`whatsapp_shop_seed_demo` links a fake demo number to the organization's real store.** Its
      "Demo: app subscribed" number (+27 00 000 0802) sells from the maintainer's own dev store.
      Harmless (Meta never sends fake numbers anything), but the seed should use only its own demo
      stores. Found 2026-11-01, WhatsApp plan Step 2.9 human checks.
- [ ] **A refused WhatsApp webhook's log line wasn't seen.** In human check M4 (a wrong App secret)
      nothing was stored, as expected, but `docker compose logs backend` showed no "refused with 403"
      line. Check whether the backend's logging prints `apps.whatsapp.views` warnings. Found 2026-11-01.
- [ ] **Section 8 of the restore-green plan has two small mistakes.** Its block 4 joins two `node`
      calls with `;`, so its exit code hides a failure of the first; the README's form uses `&&`. Its
      human check 3 points at the lint block for the "Tests:" totals, which the test block prints.
      Found 2026-11-01.
- [ ] **On the Shopify products page, the sidebar highlights both "Shopify" and "Shopify products".**
      Upstream marks an item active when the address contains its path (`pathname.includes`). Upstream
      code, cosmetic. Found 2026-10-14, Shopify plan step 11.

**Also worth a look**

- [ ] The 6.1.0 history still contains a personal ngrok address (in `shopify.app.toml`, now untracked).
      While the tunnel runs, anyone with the address reaches the local backend (behind the same HMAC
      checks and logins as production). The cheap fix is a new static ngrok domain, updated in the
      untracked `.env` and the ignored `shopify.app.toml`; rewriting public history would need a
      force-push and is not planned. Deferred by the human maintainer on 2026-10-15.
- [ ] Shopify live checks 9 to 13 (real install, token encryption, connecting from the web app,
      uninstall and reinstall, seeding refused in production) were rewritten on 2026-10-15 but haven't
      been run against a live store since 6.1.0. Shopify plan, human checks.
- [ ] To consider, not decided: the GraphQL type watcher (`graphql:generate-types:watch`) skips the
      patch steps, so every app start rewrites `gql.ts` and `graphql.ts` without the "GraphQL query not
      found" patch. Weigh a permanent difference from upstream against one `git restore` per commit.
      Details: `2026-10-07-restore-green-test-suite-plan.md`, section 9. Happened again on 2026-10-15
      (Shopify plan step 11, full run): when a commit is meant to change those files, `git restore` would
      drop that change too, so re-run `pnpm nx run webapp-api-client:graphql:generate-types` with the
      app stopped instead.
- [ ] Two order-dependent upstream backend tests: `TestAllTenantsQuery.test_all_tenants_query`
      (`apps/multitenancy`) and `TestDownloadBackupDecryptedMutation.test_download_backup_decrypted_success`
      (`apps/backup`) pass or fail depending on which tests ran before them. Upstream tests: re-run, don't
      change unasked. Found 2026-10-12.
- [ ] `webapp-shopify`'s `package.json` isn't in `.versionrc.js`'s bump list, so its version stays
      behind on every release. Found 2026-10-11.
- [ ] Console noise in passing upstream frontend tests (React `act(...)` and key warnings, MSW
      unhandled requests, Radix accessibility notices) and upstream backend deprecation warnings
      (factory_boy, drf_yasg). Not failures; upstream code. Found 2026-10-12.

---

## How to use this doc

Pick items by what the next deployment needs, not top to bottom. **P0** items are a privacy, security
or correctness gap that a real deployment would hit; **P1** items are visible to users. When an item is
started, give it a plan in `docs/superpowers/plans/`, link the plan here, and tick it when it ships,
naming the release.
