# Restore a Green Test Suite — Implementation Plan

**Date:** 2026-10-07
**Status (2026-10-09):** Step 1 (measure) done (section 2.3). Step 5.1 done. Step 2 done locally (`package.json` and
lockfile); its GREEN comes from CI on the PR. Steps 3 and 5.2 done (Run 8). Step 4 done locally (Run 9). Step 6.3 done (Run 10). Step 6.1 decided (keep upstream's skips). Step 7 done (7.1 decided, 7.2 and 7.4 GREEN in Run 13).
Step 8 decided (leave the hook unused). Step 9 decided (disable the reviewer workflow; the human maintainer clicks it). Step 10: `CHANGELOG.md` 6.1.1 entry written 2026-10-09. Final local GREEN: Runs 14 and 15
(lint and type-check 30/30, backend 1007 passed, frontend tests green apart from one known
load-sensitive upstream test that passed 5 of 5 on its own). Left: commit and push by the human
maintainer, and the CI-only checks on the PR; 6.2 moved to the Shopify
work. Not committed; no branch yet.
**Goal:** Every test in the repository runs, locally and in CI, and passes, before any new feature
starts. TDD depends on it: a RED only means something when everything else is green. With failures
already in the suite, a new failing test is lost in the noise, and nothing proves a change caused it or
fixed it.

---

## 0. Where we are (2026-10-07)

CI history (`gh run list --branch master`):

- `feat(finances): add PayFast…` (#1, 2026-10-02): Webapp green.
- `feat(finances): PayFast fixes, Cloudflare R2…` (6.0.0, #2, 2026-10-04): Webapp **red**, Backend
  **red**.
- `feat(shopify)…` (6.1.0, #3, 2026-10-07): Webapp **red**, Backend green.

So the red CI came from this fork's own recent commits, not from code inherited from upstream. What
isn't known yet is the state of the tests CI never runs (section 1), which is what step 1 measures.

---

## 1. Every test in the repository

Counted from the source: test files, and test definitions (`it`/`test` in Jest, `def test_` in
pytest). Parametrized tests run more than once, so run counts are higher (backend: 965 definitions,
1,007 tests run on 2026-10-07).

| Suite                                                 |   Files |     Tests | In CI?                                                                |
| ----------------------------------------------------- | ------: | --------: | --------------------------------------------------------------------- |
| [`backend`](../../../packages/backend/) (pytest)      |      86 |       965 | yes, [`backend.yml`](../../../.github/workflows/backend.yml)          |
| [`workers`](../../../packages/workers/) (pytest)      |       1 |         2 | yes, [`workers.yml`](../../../.github/workflows/workers.yml)          |
| [`webapp`](../../../packages/webapp/)                 |      39 |       164 | yes, [`webapp.yml`](../../../.github/workflows/webapp.yml) `test` job |
| `webapp-core`                                         |      59 |       203 | yes, `test-lib` matrix                                                |
| `webapp-tenants`                                      |      40 |       163 | yes                                                                   |
| `webapp-finances`                                     |      22 |       100 | yes                                                                   |
| `webapp-emails`                                       |      11 |        72 | yes                                                                   |
| `webapp-api-client`                                   |       6 |        42 | yes                                                                   |
| `webapp-contentful`                                   |       7 |        41 | yes                                                                   |
| `webapp-notifications`                                |       8 |        37 | yes                                                                   |
| `webapp-crud-demo`                                    |       6 |        22 | yes                                                                   |
| `webapp-documents`                                    |       2 |         8 | yes                                                                   |
| `webapp-generative-ai`                                |       1 |         4 | yes                                                                   |
| `webapp-sso`                                          |       8 |        35 | **no**: missing from the `test-lib` matrix                            |
| `webapp-ai-assistant`                                 |       1 |         7 | **no**: missing from the matrix                                       |
| `webapp-backup`                                       |       1 |         4 | **no**: missing from the matrix                                       |
| `webapp-shopify`                                      |       0 |         0 | **no**: no tests (Shopify plan step 9), missing from the matrix       |
| [`internal/tools`](../../../packages/internal/tools/) |       4 |         4 | **no**: no `test` target at all                                       |
| **Total**                                             | **302** | **1,873** | **50 tests never run in CI**                                          |

The `test-lib` matrix in [`webapp.yml`](../../../.github/workflows/webapp.yml) is a hand-written list, so a
new library is silently untested until someone adds it there.

---

## 2. Known failures

### 2.1 From CI (run 37550316919, 2026-10-07)

1. **Webapp build and type-check: `lucide-react` not found** (Node 22 and 24). CI installs with
   `pnpm install --filter=webapp...`, which installs only what `webapp` declares.
   [`packages/webapp/package.json`](../../../packages/webapp/package.json) doesn't declare
   `@sb/webapp-shopify`, so the Shopify library's dependencies are never installed in CI. A full local
   `pnpm install` hides it. Owner: **this fork (Shopify, 6.1.0)**.
2. **Webapp and webapp-contentful type-check: Contentful types.** `Asset._id` is now required
   ([`demoItemContent.component.tsx`](../../../packages/webapp-libs/webapp-contentful/src/routes/demoItem/demoItemContent.component.tsx),
   [`demoItemListItem.component.tsx`](../../../packages/webapp-libs/webapp-contentful/src/routes/demoItems/demoItemListItem/demoItemListItem.component.tsx)),
   and `ContentfulMetadata.concepts` is required
   ([`tests/factories/config.ts`](../../../packages/webapp-libs/webapp-contentful/src/tests/factories/config.ts),
   [`tests/factories/demoItem.ts`](../../../packages/webapp-libs/webapp-contentful/src/tests/factories/demoItem.ts)).
   Cause: `graphql:download-schema` also refreshed the live Contentful schema, and 6.1.0 committed it.
   Owner: **this fork (6.1.0)**.
3. **webapp-finances, Node 22 only:**
   [`editSubscription.component.spec.tsx`](../../../packages/webapp-libs/webapp-finances/src/payfast/__tests__/editSubscription.component.spec.tsx)
   can't find the button named "current plan". Passes on Node 24, so it's timing-sensitive. Owner:
   **this fork (PayFast)**.
4. **Automated code review:** the `AUTOMATED_REVIEWER` repository variable isn't set
   ([`automated-code-review.yml`](../../../.github/workflows/automated-code-review.yml)). Not code;
   configuration in GitHub.
5. **Backend red at 6.0.0.** Its failed-job log came back empty; backend is green on 6.1.0, most likely
   because 6.1.0 made the PayFast admin tests independent of `collectstatic`. Re-check in step 1.

### 2.2 From the local run (step 1; fill in)

One entry per failing test: suite, test, error, owner (fork, upstream, or configuration).

Every result below names the exact command that produced it, so it can be re-run to check.

**Run 1, 2026-10-07, five suites** (the ones not covered by section 2.1; the rest still to run). Command,
from the repository root:

```shell
for p in webapp-sso webapp-ai-assistant webapp-backup webapp-finances webapp-contentful; do echo "=== $p"; pnpm nx run $p:test --watchAll=false --skip-nx-cache 2>&1 | tail -20; done
```

Results:

- `webapp-ai-assistant`: 1 file, 7 passed.
- `webapp-backup`: 1 file, 4 passed.
- `webapp-finances`: 22 files, 100 passed (Node 24 locally; CI's failure 3 is on Node 22).
- `webapp-contentful`: 7 files, 41 passed. Its type-check still fails (failure 2); this command runs
  only the tests.
- **`webapp-sso`: 8 files failed to load, 0 tests run (RED).** Its error, from
  `pnpm nx run webapp-sso:test --watchAll=false --skip-nx-cache 2>&1 | grep -m1 -A30 "Test suite failed to run"`:
  `Could not locate module react-markdown mapped as …/node_modules/react-markdown/react-markdown.min.js`.
  [`webapp-sso/jest.config.ts`](../../../packages/webapp-libs/webapp-sso/jest.config.ts) maps
  `react-markdown` to the root `node_modules`, where pnpm never puts it. Owner: **upstream**. The file is
  unchanged since upstream's `release/5.0.0`, and upstream's CI doesn't run this library either, so the
  breakage was never noticed.

**Run 2, 2026-10-07, `webapp-sso` after step 5.1's fix (GREEN).** Command:

```shell
pnpm nx run webapp-sso:test --watchAll=false --skip-nx-cache 2>&1 | tail -20
```

Result: 8 files, 35 passed, 0 failed.

**Run 3, 2026-10-07, the remaining Jest suites: inconclusive.** Command:

```shell
for p in webapp webapp-core webapp-tenants webapp-emails webapp-api-client webapp-notifications webapp-crud-demo webapp-documents webapp-generative-ai webapp-libs-webapp-shopify; do echo "=== $p"; pnpm nx run $p:test --watchAll=false --skip-nx-cache 2>&1 | grep -E "^ *FAIL |^Test Suites:|^Tests:|No tests found"; done
```

Result: no summary lines printed for the first nine suites. The `grep` pattern anchored on the start of
the line (`^`), and Nx's output starts each line with colour codes, so nothing matched. Not a test
result; re-run as Run 6 with the output saved to files.

- `webapp-libs-webapp-shopify`: `No tests found, exiting with code 1`. **RED**: a library with no tests
  fails its own `test` target (Shopify plan step 9's missing component tests). It would fail CI once
  step 7 adds it to the matrix.

**Run 5, 2026-10-07, workers, fresh.** Command:

```shell
pnpm nx run workers:test --skip-nx-cache 2>&1 | tail -15
```

Result: 2 passed, 0 failed (one SQLAlchemy warning about a redeclared `ContentModel` class).

**Run 6, 2026-10-07, the nine Jest suites Run 3 failed to measure.** Command (each suite's output saved
in the gitignored `logs/` folder; the exit code is the pass/fail signal):

```shell
for p in webapp webapp-core webapp-tenants webapp-emails webapp-api-client webapp-notifications webapp-crud-demo webapp-documents webapp-generative-ai; do pnpm nx run $p:test --watchAll=false --skip-nx-cache > logs/$p.log 2>&1; echo "$p exit code: $?"; done
```

Counts read from the logs with
`sed 's/\x1b\[[0-9;]*m//g' logs/<suite>.log | grep -E "^(Test Suites|Tests):"`. Every exit code 0:

- `webapp`: 38 files passed, 1 skipped; 164 passed, 2 skipped.
- `webapp-core`: 59 files; 203 passed.
- `webapp-tenants`: 40 files; 163 passed, 2 skipped.
- `webapp-emails`: 11 files; 72 passed.
- `webapp-api-client`: 6 files; 42 passed.
- `webapp-notifications`: 8 files; 37 passed.
- `webapp-crud-demo`: 6 files; 22 passed.
- `webapp-documents`: 2 files; 8 passed.
- `webapp-generative-ai`: 1 file; 4 passed.

The 4 skipped tests are marked `it.skip` in upstream's own code, in files this fork hasn't changed
(found with `grep -rn "it.skip(" packages/webapp/src packages/webapp-libs/webapp-tenants/src`):

- [`twoFactorAuthForm.component.spec.tsx`](../../../packages/webapp/src/shared/components/auth/twoFactorAuthForm/__tests__/twoFactorAuthForm.component.spec.tsx):
  "should open 2FA setup modal", "should disable 2FA"
- [`addSSOConnectionModal.component.spec.tsx`](../../../packages/webapp-libs/webapp-tenants/src/routes/tenantSettings/tenantSecuritySettings/components/__tests__/addSSOConnectionModal.component.spec.tsx):
  "should create connection and show success step when form is valid"
- [`passkeysCard.component.spec.tsx`](../../../packages/webapp-libs/webapp-tenants/src/routes/tenantSettings/tenantSecuritySettings/components/__tests__/passkeysCard.component.spec.tsx):
  "should call delete and show toast on success"

**Run 7, 2026-10-09, `lint` and `type-check` for the 15 frontend projects.** Command (logs in the
gitignored `logs/` folder as `logs/<project>-<check>.log`; the exit code is the pass/fail signal):

```shell
for p in webapp webapp-core webapp-tenants webapp-finances webapp-emails webapp-api-client webapp-contentful webapp-notifications webapp-crud-demo webapp-documents webapp-generative-ai webapp-sso webapp-ai-assistant webapp-backup webapp-libs-webapp-shopify; do for t in lint type-check; do pnpm nx run $p:$t --skip-nx-cache > logs/$p-$t.log 2>&1; echo "$p $t exit code: $?"; done; done
```

Results: `lint` passed (exit code 0) for all 15. `type-check` passed for 12 and failed (exit code 1)
for three. The errors were read with
`sed 's/\x1b\[[0-9;]*m//g' logs/<project>-type-check.log | grep -E "error TS"`:

- `webapp`: the two `Asset._id` errors (failure 2).
- `webapp-contentful`: the same two, plus three `ContentfulMetadata.concepts` errors in its test
  factories (failure 2).
- **`webapp-sso`: 192 errors, all `TS6059: File … is not under 'rootDir'`.**
  [`webapp-sso/tsconfig.json`](../../../packages/webapp-libs/webapp-sso/tsconfig.json) sets
  `"rootDir": "src"`, so TypeScript requires every checked file to be inside `webapp-sso/src`. The
  library imports webapp-core, webapp-tenants and webapp-api-client from source, so all their files
  break that rule. Owner: **upstream**: the file is unchanged since `release/5.0.0`, and no other
  library sets `rootDir` (compare
  [`webapp-backup/tsconfig.json`](../../../packages/webapp-libs/webapp-backup/tsconfig.json)).

**Run 8, 2026-10-09, GREEN for steps 3 and 5.2.** Command:

```shell
for p in webapp webapp-contentful webapp-sso; do pnpm nx run $p:type-check --skip-nx-cache > logs/$p-type-check.log 2>&1; echo "$p type-check exit code: $?"; done; for p in webapp webapp-contentful; do pnpm nx run $p:test --watchAll=false --skip-nx-cache > logs/$p.log 2>&1; echo "$p test exit code: $?"; done
```

Results: all five exit codes 0. Type-check green for `webapp`, `webapp-contentful` and `webapp-sso`.
Tests, read with `sed 's/\x1b\[[0-9;]*m//g' logs/<suite>.log | grep -E "^(Test Suites|Tests):"`:
`webapp` 164 passed, 2 skipped (same as Run 6, so the `gql.ts` patch broke nothing);
`webapp-contentful` 41 passed.

**Run 11, 2026-10-09, `internal/tools`' 4 tests (step 7.1).** No `test` target exists, so Jest was
run directly with the package's own config. Command:

```shell
pnpm exec jest --config packages/internal/tools/jest.config.ts --watchAll=false > logs/tools-test.log 2>&1; echo "tools test exit code: $?"
```

Result: exit code 1. Read with
`sed 's/\x1b\[[0-9;]*m//g' logs/tools-test.log | grep -E "PASS|FAIL|Tests:|Test Suites:"` and
`grep -A12 "Test suite failed to run"`: 2 files passed, 2 failed to compile (2 tests passed, 0 failed,
2 files never loaded).

- Passed: `src/executors/build/executor.spec.ts`, `src/generators/tools/generator.spec.ts`.
- Failed to compile: `src/generators/webapp-lib/generator.spec.ts` (`TS2305: Module "./schema" has no
exported member 'ToolsGeneratorSchema'`), and `src/executors/setup/executor.spec.ts` (`TS2741:
Property 'cwd' is missing`, `TS2554: Expected 2 arguments, but got 1`).
- Owner: **upstream**: `git diff --quiet upstream/master -- packages/internal/tools/src` reports
  identical. Upstream never gave `tools` a `test` target, so these never ran and drifted from the
  code. They test the repo's internal scaffolding (library generators), not the product.

**Run 14, 2026-10-09, final GREEN part 1: `lint` and `type-check` for all 15 frontend projects, after
every fix.** Command:

```shell
for p in webapp webapp-core webapp-tenants webapp-finances webapp-emails webapp-api-client webapp-contentful webapp-notifications webapp-crud-demo webapp-documents webapp-generative-ai webapp-sso webapp-ai-assistant webapp-backup webapp-libs-webapp-shopify; do for t in lint type-check; do pnpm nx run $p:$t --skip-nx-cache > logs/$p-$t.log 2>&1; echo "$p $t exit code: $?"; done; done
```

Result: all 30 exit codes 0, including the three type-checks that failed in Run 7 (`webapp`,
`webapp-contentful`, `webapp-sso`).

Why a loop and not `pnpm nx run-many -t lint type-check --projects="webapp*"`: `run-many` runs 3 tasks
at once by default (`nx.json` sets no `parallel`), and three TypeScript compiler runs side by side
exhausted the memory of the human maintainer's 15 GB machine (with the Docker stack running) and froze
it. The loop runs one task at a time, which was proven safe on that machine by Runs 6 and 7.
`--parallel=1` should behave the same but wasn't tried, because a freeze needs a restart.

**Run 14 part 2, 2026-10-09: backend, then the 14 frontend test suites.** Run by the human maintainer
in this order: backend first, then the lint and type-check loop again (30 of 30 green, as in part 1),
then the tests. Commands:

```shell
pnpm nx run backend:test --skip-nx-cache > logs/backend-test.log 2>&1; echo "backend exit code: $?"
for p in webapp webapp-core webapp-tenants webapp-finances webapp-emails webapp-api-client webapp-contentful webapp-notifications webapp-crud-demo webapp-documents webapp-generative-ai webapp-sso webapp-ai-assistant webapp-backup; do pnpm nx run $p:test --watchAll=false --maxWorkers=2 --skip-nx-cache > logs/$p.log 2>&1; echo "$p test exit code: $?"; done
```

Results:

- `backend`: exit code 0, 1007 passed in 13:50 (from `logs/backend-test.log`).
- Frontend tests: 13 of 14 exit code 0. **`webapp-tenants` exit code 1**: 1 failed, 162 passed, 2
  skipped. "TenantMembersList: Component › should render list of memberships"
  ([`tenantMembersList.component.spec.tsx`](../../../packages/webapp-libs/webapp-tenants/src/components/tenantMembersList/__tests__/tenantMembersList.component.spec.tsx)),
  `Expected number of calls: >= 1, Received number of calls: 0`.

**Run 15, 2026-10-09, that test file alone, 5 times.** Command:

```shell
for i in $(seq 1 5); do pnpm nx run webapp-tenants:test --watchAll=false --skip-nx-cache --testPathPattern=tenantMembersList > logs/tenants-members-run$i.log 2>&1; echo "run $i exit code: $?"; done
```

Result: 5 of 5 exit code 0; runs 1 and 5 checked in their logs (`PASS …tenantMembersList.component.spec.tsx`,
9 passed). So it's **intermittent under load**, not broken. The test is upstream's (identical to
`upstream/master`). It waits with `waitForApolloMocks()`, a shared upstream helper in
[`webapp-api-client/src/tests/utils/rendering.tsx`](../../../packages/webapp-libs/webapp-api-client/src/tests/utils/rendering.tsx)
whose wait is fixed at 3 seconds (`waitFor(…, { timeout: 3000 })`). In Run 14 it ran right after the
backend's Docker run, with Jest capped at 2 workers, and once took longer than that. It passed in Run 6,
in Run 15, and in CI on Node 22 and 24. **Decided 2026-10-09: leave it as upstream has it** (no change
to the test or the shared helper); a known load-sensitive test (section 2.3), and section 8 runs the
frontend tests before the backend.

### 2.3 Measured (step 1 complete, 2026-10-09)

- **Green:** backend (1007), workers (2), and all 14 Jest suites that have tests, run fresh with
  `--skip-nx-cache` (Runs 1, 2, 4, 5, 6).
- **Red or not run:**
  - `webapp-shopify` has no tests, so its `test` target fails (Run 3).
  - 4 upstream tests are skipped (Run 6).
  - `internal/tools` has 4 upstream tests and no `test` target; 2 of them no longer compile (Run 11).
    Left unwired by decision (step 7.1): a known gap, not part of the suite.
  - Known load-sensitive upstream test: `webapp-tenants`' "should render list of memberships" can
    exceed `waitForApolloMocks`' fixed 3-second wait on a busy machine (Runs 14 and 15). Left as
    upstream has it (decided 2026-10-09).
  - The CI-only failures 1 to 4 (section 2.1).
- **Lint and type-check (Run 7):** lint green for all 15 frontend projects. Type-check red for
  `webapp` and `webapp-contentful` (failure 2, step 3) and `webapp-sso` (`rootDir`, step 5.2).

**Run 4, 2026-10-07, workers and backend.** Command, then `tail -15` of each log:

```shell
pnpm nx run workers:test 2>&1 | tee workers-test.log; pnpm nx run backend:test 2>&1 | tee backend-test.log
```

Results:

- `backend`: 1007 passed, 0 failed, in 18:57. Nx replayed 3 of its 5 tasks from cache (the setup and
  build steps); the test task itself ran.
- `workers`: 2 passed, but **replayed from the Nx cache** ("3 out of 3 tasks"), so not a fresh result.
  To re-run with `--skip-nx-cache` (Run 5).

Lesson: every test command in this plan uses `--skip-nx-cache`, or Nx can replay an old result as if it
were new.

---

## 3. Touching upstream code (exception granted by the human maintainer, 2026-10-07)

The standing rule is to leave the original author's code alone (section 3 of
[`agents.md`](../agents.md)). For this plan only, the human maintainer allows changes to upstream files
where that's what turns the suite green, on three conditions:

1. A failure is proven to come from upstream code (it also fails on a clean checkout of the upstream
   commit the fork is based on) before any upstream file is changed.
2. The fix is the smallest that works, preferring the test or the configuration over the logic.
3. Every upstream file changed is listed in section 6, so the next `upstream/master` merge knows where
   to expect conflicts.

None of the CI failures (section 2.1) needs it: all are in fork code or configuration. The first case
that does is `webapp-sso`'s test setup (section 2.2, step 5.1).

---

## 4. Rules that keep it green

- A test upstream skips stays skipped in this fork (decided 2026-10-09, step 6.1). Upstream's team is
  far larger, so its reasons win even when undocumented. Re-check after each `upstream/master` merge:
  if upstream un-skips a test, the merge brings that in.

- Test and CI logs are saved in the project's `logs/` folder, which `.gitignore` excludes, never in the
  project root (where `git add .` would commit them) or outside the project.

- The CI test matrix lists every library that has a `test` target. A test (step 7) checks this, so a new
  library can't be left out silently.
- Every Nx project with test files has a `test` target.
- After `graphql:download-schema`, keep only the `api.graphql` changes; restore `contentful.graphql`
  unless the change is deliberate and its type errors are fixed in the same change.

---

## 5. Proposed Changes (implementation steps)

Branch: `feature/restore-green-test-suite` off `master`. Strict TDD (section 2 of
[`agents.md`](../agents.md)). For a broken test, the test failing is the RED: fix it, and the same
command going green is the GREEN.

1. **Measure.** Run every suite locally once (section 8, "Automated", the full list), record each
   failure in section 2.2 with its owner, and update steps 5 and 6 from it.
2. **Webapp: declare the Shopify library** (failure 1).
   - RED: CI run 37550316919 (2026-10-07), `Webapp / build`: `Rollup failed to resolve import
"lucide-react"`, from the command CI runs, `pnpm install --filter=webapp...` then
     `pnpm nx run webapp:build`. `grep -rln "@sb/webapp-shopify" packages/webapp/src` finds it imported
     in `app.component.tsx` and `routes.ts`, and it's missing from `webapp`'s `package.json`. It's the
     only library imported but not declared (`webapp-sso` isn't imported by `webapp`).
   - Fix (2026-10-07): `"@sb/webapp-shopify": "workspace:*"` added to
     [`packages/webapp/package.json`](../../../packages/webapp/package.json), then `pnpm install` to
     update `pnpm-lock.yaml`.
   - `pnpm install` (2026-10-09): `git diff --stat pnpm-lock.yaml` shows 3 lines added, the
     `'@sb/webapp-shopify'` entry with `version: link:../webapp-libs/webapp-shopify` under `webapp`;
     nothing else changed.
   - GREEN: CI's `Webapp / build` on the PR (it can't be reproduced locally without a clean clone,
     because a full local install hides the missing declaration).
3. ✅ **Contentful schema** (failure 2). GREEN 2026-10-09, Run 8.
   - RED: CI run 37550316919 (2026-10-07), `webapp-contentful: Type check`, 5 errors (`Asset._id`
     twice, `ContentfulMetadata.concepts` three times), and `Webapp / test: Type check`, the two
     `Asset._id` errors.
   - Cause: `git log --oneline -- packages/webapp-libs/webapp-contentful/graphql/schema/contentful.graphql`
     shows the Shopify commit `13aa4660` as the only fork commit that changed the file; before it, the
     last change was upstream's (`e6c6dc39`). So `0a94b11e` (6.0.0) holds the upstream version.
   - Then: restore it with
     `git show 0a94b11e:packages/webapp-libs/webapp-contentful/graphql/schema/contentful.graphql > packages/webapp-libs/webapp-contentful/graphql/schema/contentful.graphql`,
     run `pnpm nx run webapp-api-client:graphql:generate-types`, and check `git diff` of the generated
     files keeps only the Shopify additions.
   - Done 2026-10-09 with:
     `git show 0a94b11e:packages/webapp-libs/webapp-contentful/graphql/schema/contentful.graphql > packages/webapp-libs/webapp-contentful/graphql/schema/contentful.graphql && pnpm nx run webapp-api-client:graphql:generate-types > logs/generate-types.log 2>&1; echo "generate-types exit code: $?"`
     → exit code 0.
   - Checked with `git diff --stat packages/webapp-libs/` and `grep`: `graphql.ts` lost 235 lines of
     the newer Contentful types, no line containing `Shopify` was removed, and 51 Shopify references
     remain.
   - Side effect: `gql.ts` changed 10 lines. The documented `generate-types` ends with
     [`patch-gql.js`](../../../packages/webapp-libs/webapp-api-client/scripts/patch-gql.js), which makes a
     query missing from the generated map **throw** ("GraphQL query not found … run generate-types")
     instead of silently returning `{}`. Upstream's committed `gql.ts`, 6.0.0 and 6.1.0 were all
     generated without that step. Kept (recommended): it's the repo's own documented output. The
     `webapp` tests are re-run in the GREEN to make sure nothing relied on the silent `{}`.
   - GREEN: Run 8 (`webapp` and `webapp-contentful` type-check, plus `webapp` tests).
4. ✅ **Flaky PayFast test on Node 22** (failure 3). Local GREEN 2026-10-09 (Run 9): 10 of 10 on
   Node 20. Command:
   `for i in $(seq 1 10); do pnpm nx run webapp-finances:test --watchAll=false --skip-nx-cache --testPathPattern="payfast/.*editSubscription" > logs/webapp-finances-run$i.log 2>&1; echo "run $i exit code: $?"; done`
   → every exit code 0. Runs 1 and 10 checked in their logs: `PASS
src/payfast/__tests__/editSubscription.component.spec.tsx`, 4 passed, so the filter really ran the
   file. (A first attempt typed the filter with `__tests__`, which arrived as `tests` and matched no file:
   10 × "No tests found". Filters are now written without underscore pairs.) CI's Node 22 and 24 runs
   remain the final check.
   - RED: CI run 37550316919 (2026-10-07), `test-lib (22, webapp-finances)`: "PayFast edit subscription ›
     sends a free organisation to PayFast to start the chosen plan", at
     `editSubscription.component.spec.tsx:68`, `Unable to find an accessible element with the role
"button" and name /current plan/i`. Found in the saved CI log with
     `sed 's/\x1b\[[0-9;]*m//g' logs/webapp-shopify.log | grep -E "●|editSubscription.component.spec.tsx:[0-9]+"`.
   - Cause (fork test code, not the page):
     [`editSubscription.component.tsx`](../../../packages/webapp-libs/webapp-finances/src/payfast/routes/editSubscription.component.tsx)
     draws the plan cards from the plans query and marks the current plan from a second query (the
     subscription), which can arrive later. The test waited only for the card, then checked for the
     "Current plan" button with `getByRole`, which doesn't wait. The race showed up only on CI's Node 22
     runner; locally (the human maintainer runs pnpm on Node 20) and on CI's Node 24 it passed. The fix
     is plain Testing Library code and doesn't depend on the Node version.
   - Fix (2026-10-09): `findByRole` (waits until the button appears) instead of `getByRole` for the
     three checks that depend on the subscription, lines 68, 110 and 112 of
     [`editSubscription.component.spec.tsx`](../../../packages/webapp-libs/webapp-finances/src/payfast/__tests__/editSubscription.component.spec.tsx),
     per the webapp testing guide's "Test passes locally but fails in CI".
   - GREEN: 10 runs in a row on Node 20, the human maintainer's usual version (Run 9), then CI's
     `test-lib (22, webapp-finances)` and `(24, …)`. A local Node 22 run was considered and dropped
     (2026-10-09): the failure was a timing race that happened to show on CI's Node 22 runner, not
     something Node 22 causes, so CI is the real check for 22 and 24.
5. **Failures found in step 1 in the suites CI doesn't run** (`webapp-sso`, `webapp-ai-assistant`,
   `webapp-backup`). One sub-step per failure, with its owner and, if upstream, the evidence section 3
   asks for.
   1. ✅ **`webapp-sso` test setup** (section 2.2, upstream).
      - RED (2026-10-07, section 2.2 run 1): 8 of 8 test files failed to load. Command:
        `pnpm nx run webapp-sso:test --watchAll=false --skip-nx-cache 2>&1 | tail -20`
      - Fix: map `react-markdown` and `remark-gfm` to webapp-core's mocks, as
        [`webapp-backup/jest.config.ts`](../../../packages/webapp-libs/webapp-backup/jest.config.ts) does.
      - GREEN (2026-10-07, section 2.2 run 2): 8 files, 35 passed. Same command.
   2. ✅ **`webapp-sso` type-check** (section 2.2 Run 7, upstream). GREEN 2026-10-09, Run 8.
      - RED (2026-10-09, Run 7): 192 × `TS6059 … is not under 'rootDir'`. Command:
        `pnpm nx run webapp-sso:type-check --skip-nx-cache > logs/webapp-sso-type-check.log 2>&1; echo $?`
      - Fix: remove `"rootDir": "src"` from
        [`webapp-sso/tsconfig.json`](../../../packages/webapp-libs/webapp-sso/tsconfig.json), like every
        other library. Smallest change; if real type errors appear once `rootDir` is gone, each becomes a
        further sub-step.
      - Fix made 2026-10-09.
      - GREEN: Run 8, `webapp-sso` type-check exit code 0.
6. **Anything else step 1 finds**, same format.
   1. ✅ **4 upstream tests skipped with `it.skip`** (section 2.2, Run 6). **Decided 2026-10-09: keep
      all four skipped, exactly as upstream has them; no code change.** Each file was checked against
      `upstream/master`, and upstream skips the same tests (2 in `twoFactorAuthForm`, with a comment
      about React 19 strict mode and Apollo Client 4; 1 in `addSSOConnectionModal` and 1 in
      `passkeysCard`, without one). The human maintainer's reasoning: upstream has about 30
      contributors, this fork has two people and an AI agent, so upstream's reasons for a skip are the
      better bet even when they aren't written down. Not a failure: skipped tests don't run, so they
      don't make the suite red.
   2. **`webapp-shopify` has no tests** (Run 3). **Moved out of this plan (decided 2026-10-07):** done
      next, as the Shopify plan's step 9, right after this plan is committed. Until then its `test` target
      fails, so step 7 doesn't add it to CI; the Shopify work adds it once its tests exist.
   3. **Flaky upstream Stripe test**, found 2026-10-09 while checking step 4 on Node 20. Command:
      `pnpm nx run webapp-finances:test --watchAll=false --skip-nx-cache --testPathPattern=editSubscription > logs/webapp-finances-edit.log 2>&1; echo "exit code: $?"`
      → exit code 1; read with
      `sed 's/\x1b\[[0-9;]*m//g' logs/webapp-finances-edit.log | grep -E "●|Tests:|spec.tsx:[0-9]+"`.
      - The pattern matched 3 files. The two PayFast ones passed, including step 4's fix. The failure
        was "EditSubscription: Component › plan is changed sucessfully › should show success message
        and redirect to my subscription page", at line 116 of
        [`routes/editSubscription/__tests__/editSubscription.component.spec.tsx`](../../../packages/webapp-libs/webapp-finances/src/routes/editSubscription/__tests__/editSubscription.component.spec.tsx):
        `expect(monthlyButton).toBeDisabled()`. It passed in Run 1 and in CI, so it's intermittent.
      - Owner: **upstream**. `git diff --quiet upstream/master -- <file>` reports it identical to
        upstream; last changed in `release/5.0.0`.
      - Cause: after clicking "Select", the test checks that the button is disabled while the plan
        change is being sent. The mocked answer comes back almost instantly, so the button is sometimes
        enabled again before the check runs. Waiting can't help, because the state is momentary.
      - Proposed fix: `delay: 100` on that test's mutation mock (`fillChangeSubscriptionMutation`, line
        61); Apollo's mocks support a delay in milliseconds. This makes "sending" last long enough to
        check. Test-only change.
      - Fix made 2026-10-09: that one test's mock wrapped as
        `{ ...fillChangeSubscriptionMutation(…), delay: 100 }`, with a comment saying why. The helper
        itself and the other tests are unchanged.
      - ✅ GREEN 2026-10-09 (Run 10): 10 of 10 on Node 20, and `webapp-finances` type-check exit code 0. Command:
        `for i in $(seq 1 10); do pnpm nx run webapp-finances:test --watchAll=false --skip-nx-cache --testPathPattern="routes/editSubscription/.*editSubscription" > logs/webapp-finances-stripe-run$i.log 2>&1; echo "run $i exit code: $?"; done; pnpm nx run webapp-finances:type-check --skip-nx-cache > logs/webapp-finances-type-check.log 2>&1; echo "type-check exit code: $?"`
        Runs 1 and 10 checked in their logs: `PASS
src/routes/editSubscription/__tests__/editSubscription.component.spec.tsx`, 2 passed.
7. **Make CI run every test.** Sub-steps, in order:
   1. ✅ **Measure `internal/tools`' 4 tests** (Run 11): 2 pass, 2 don't compile, all upstream and never
      run by upstream. **Decided 2026-10-09: leave them unwired, as upstream has them; no change.** Same
      reasoning as step 6.1: upstream chose not to run them. They test internal scaffolding, not the
      product. Recorded as a known gap in section 2.3.
   2. **Add `webapp-sso`, `webapp-ai-assistant` and `webapp-backup` to the `test-lib` matrix** in
      [`webapp.yml`](../../../.github/workflows/webapp.yml). All three are green locally (Runs 1, 2, 7,
      8). Done 2026-10-09: appended to the matrix, after `webapp-tenants`. GREEN: Run 13 locally, then
      their `test-lib` jobs on the PR. Their SonarCloud keys weren't added: that step is disabled
      (`if: false`).
   3. ~~**`internal/tools`:** a `test` target and a CI step.~~ Dropped by the 7.1 decision.
   4. **A check that no library is left out of the matrix:** a small script that lists every
      `packages/webapp-libs/*` project with a `test` target and fails if one is missing from
      `webapp.yml`. Written test-first: run it against today's matrix (RED: it names `webapp-sso`,
      `webapp-ai-assistant`, `webapp-backup`), then GREEN after 7.2. Until the Shopify work adds tests,
      `webapp-shopify` is the one allowed exception, listed in the script with a link to the Shopify plan.
      - Written 2026-10-09:
        [`check-test-lib-matrix.js`](../../../.github/workflows/scripts/check-test-lib-matrix.js) (the
        guard) and
        [`check-test-lib-matrix.test.js`](../../../.github/workflows/scripts/check-test-lib-matrix.test.js)
        (5 checks of the guard's own logic on made-up inputs, so a broken guard can't give a false
        GREEN), shaped like the existing `dedupe-review-comment.js` and its test.
      - RED 2026-10-09 (Run 12). Command:
        `node .github/workflows/scripts/check-test-lib-matrix.test.js; node .github/workflows/scripts/check-test-lib-matrix.js; echo "check exit code: $?"`
        → `all assertions passed`, then
        `Missing from the test-lib matrix in .github/workflows/webapp.yml: webapp-ai-assistant, webapp-backup, webapp-sso`,
        `check exit code: 1`.
      - CI: a new `test-lib-matrix` job at the end of
        [`webapp.yml`](../../../.github/workflows/webapp.yml) runs both files on every push. It's a
        separate job, so upstream's jobs are untouched, and it needs only Node (`actions/setup-node`),
        not the pnpm install.
      - ✅ GREEN 2026-10-09 (Run 13), the same command after step 7.2 →
        `all assertions passed`,
        `All 13 webapp libraries with a test target are in the test-lib matrix. Allowed to be missing: webapp-shopify (no tests yet).`,
        `check exit code: 0`. There are 14 folders in `packages/webapp-libs/`, all with a `test` target:
        13 in the matrix plus `webapp-shopify`. Final check: the `test-lib-matrix` job on the PR.

   Moved to the Shopify work (decided 2026-10-07, with step 6.2): renaming the Nx project
   `webapp-libs-webapp-shopify` to `webapp-shopify` (the matrix uses the project name as the folder
   name, `projectBaseDir`, so the two must match), and adding it to the matrix once it has tests.

8. ✅ **Unused `useLanguageFromParams`. Decided 2026-10-09: leave the folder as it is, unused; no code
   change.** The hook reads the URL's first segment (`useLocale()`, or the default language) and calls
   `setLanguage` with it. The 6.1.0 redirect already does that for real language codes and redirects
   everything else, so restoring the call would set the language to words like `shopify` again.
   Deleting it would be one more change to upstream files and a likely conflict on upstream merges;
   leaving it adds no difference from upstream. Original wording of this step:
   **Unused `useLanguageFromParams`** (left over from 6.1.0). Read what upstream's
   [`useLanguageFromParams`](../../../packages/webapp/src/app/providers/validRoutesProvider/useLanguageFromParams/)
   does, then either call it again from
   [`validRoutesProviders.tsx`](../../../packages/webapp/src/app/providers/validRoutesProvider/validRoutesProviders.tsx)
   or delete it. The human maintainer decides.
9. ✅ **Automated code review. Decided 2026-10-09: disable the workflow in GitHub** (repository →
   Actions → "Automated code review" → "…" → Disable workflow). It needs the `AUTOMATED_REVIEWER`
   variable (`codex` is the only reviewer wired up) and an `OPENAI_API_KEY` secret, so each review costs
   money. Disabling it is free, needs no code change, and can be undone with Enable workflow. Recorded in
   `CLAUDE.md`'s "Automated reviewer" row. Human check: the PR's checks no longer list "Automated code
   review". Original wording of this step: **Automated code review** (failure 4, human action): set `AUTOMATED_REVIEWER` to `codex` under
   GitHub → Settings → Secrets and variables → Actions → Variables (its plan:
   [`2026-09-01-automated-pr-review-plan.md`](2026-09-01-automated-pr-review-plan.md)), or disable the
   workflow until it's configured. Record the choice in `CLAUDE.md`'s "Automated reviewer" row.
10. **Release bookkeeping** (decided 2026-10-09):
    - `CHANGELOG.md`: 6.1.1 entry written.
    - Version numbers: `package.json` files were still `6.0.0` and no `6.1.0` tag existed, so 6.1.0's
      bump was missed too. On the feature branch:
      `npx standard-version --release-as 6.1.1 --skip.changelog --skip.tag --skip.commit` (sets 6.1.1 in
      the files listed in `.versionrc.js`; `--skip.commit` so the README protocol's single commit
      includes it). Done 2026-10-09 on `feature/restore-green-test-suite`: 23 `package.json`-type files
      changed by one line each (`git diff --stat -- '*.json'`), no commit made (`git log --oneline -1`
      still `13aa4660`), no tag. After merging: tag the merge commit `6.1.1`, and tag the 6.1.0 merge commit
      `13aa4660` as `6.1.0` so the history has both.
    - README Testing section corrected (2026-10-09): it had been written in 6.1.0, not by upstream, with
      a `docker compose exec webapp` command for a service that doesn't exist, a `--testFile` flag
      `backend:test` doesn't accept, and `exec … uv run pytest` running with the app's `.env`. Replaced
      with this plan's proven commands.

    Original wording: **Release bookkeeping.** Fixes only, so a patch: **6.1.1** proposed, under `### Bug Fixes`. The
    human maintainer picks the number.

---

## 6. File Summary

Expected (finalized after step 1):

- [`packages/webapp/package.json`](../../../packages/webapp/package.json), `pnpm-lock.yaml`: the
  `@sb/webapp-shopify` dependency
- [`contentful.graphql`](../../../packages/webapp-libs/webapp-contentful/graphql/schema/contentful.graphql)
  and the generated types in
  [`webapp-api-client/src/graphql/__generated`](../../../packages/webapp-libs/webapp-api-client/src/graphql/__generated/)
- [`editSubscription.component.spec.tsx`](../../../packages/webapp-libs/webapp-finances/src/payfast/__tests__/editSubscription.component.spec.tsx)
  (fork code)
- [`webapp-shopify/project.json`](../../../packages/webapp-libs/webapp-shopify/project.json) and the
  references to its project name
- [`.github/workflows/webapp.yml`](../../../.github/workflows/webapp.yml),
  [`.github/workflows/tools.yml`](../../../.github/workflows/tools.yml),
  [`internal/tools/project.json`](../../../packages/internal/tools/project.json)
- `CHANGELOG.md` and the versions bumped by `standard-version`

Upstream files changed under the section 3 exception:

- [`packages/webapp-libs/webapp-sso/jest.config.ts`](../../../packages/webapp-libs/webapp-sso/jest.config.ts):
  `moduleNameMapper` for `react-markdown` and `remark-gfm` (step 5.1)
- [`packages/webapp-libs/webapp-sso/tsconfig.json`](../../../packages/webapp-libs/webapp-sso/tsconfig.json):
  `"rootDir": "src"` removed (step 5.2)
- [`webapp-finances/src/routes/editSubscription/__tests__/editSubscription.component.spec.tsx`](../../../packages/webapp-libs/webapp-finances/src/routes/editSubscription/__tests__/editSubscription.component.spec.tsx):
  `delay: 100` on one test's mutation mock (step 6.3)

---

## 7. User stories

Not user-facing: this is about the development workflow.

---

## 8. Verification Plan

### Automated

Every check, the way that worked on the human maintainer's machine (Runs 14 and 15). Run the four
commands one after another from the repository root, in this order, never side by side:

- One task at a time. `pnpm nx run-many` runs 3 at once by default and froze the machine (Run 14).
- Frontend tests before the backend, so the load-sensitive `webapp-tenants` test (section 2.3) doesn't
  run on a machine still busy from Docker.
- `--skip-nx-cache` so Nx really runs everything; `--maxWorkers=2` caps Jest's worker processes.
- Output goes to the gitignored `logs/` folder; each command prints one `exit code` line per check
  (0 = passed). Read counts with `sed 's/\x1b\[[0-9;]*m//g' logs/<file>.log | grep -E "^(Test Suites|Tests):"`.
- Docker must be running for the last two (backend and workers).

1. Lint and type-check, 15 frontend projects (30 lines):

```shell
mkdir -p logs; for p in webapp webapp-core webapp-tenants webapp-finances webapp-emails webapp-api-client webapp-contentful webapp-notifications webapp-crud-demo webapp-documents webapp-generative-ai webapp-sso webapp-ai-assistant webapp-backup webapp-libs-webapp-shopify; do for t in lint type-check; do pnpm nx run $p:$t --skip-nx-cache > logs/$p-$t.log 2>&1; echo "$p $t exit code: $?"; done; done
```

2. Tests, the 14 frontend projects that have tests (`webapp-shopify` has none yet):

```shell
for p in webapp webapp-core webapp-tenants webapp-finances webapp-emails webapp-api-client webapp-contentful webapp-notifications webapp-crud-demo webapp-documents webapp-generative-ai webapp-sso webapp-ai-assistant webapp-backup; do pnpm nx run $p:test --watchAll=false --maxWorkers=2 --skip-nx-cache > logs/$p.log 2>&1; echo "$p test exit code: $?"; done
```

3. Backend (formatter, migrations check, about 1,000 tests; about 15 to 20 minutes) and workers:

```shell
pnpm nx run backend:test --skip-nx-cache > logs/backend-test.log 2>&1; echo "backend exit code: $?"; pnpm nx run workers:test --skip-nx-cache > logs/workers-test.log 2>&1; echo "workers exit code: $?"
```

4. The CI test-list guard (step 7.4):

```shell
node .github/workflows/scripts/check-test-lib-matrix.test.js; node .github/workflows/scripts/check-test-lib-matrix.js; echo "check exit code: $?"
```

When the Shopify work renames its Nx project, use `webapp-shopify` instead of
`webapp-libs-webapp-shopify`, and add it to command 2 once it has tests.

### Human checks

1. Open the PR's checks on GitHub → every check is green, none skipped except the ones the automated
   reviewer skips by design.
2. The `test-lib` jobs include `webapp-sso`, `webapp-ai-assistant`, `webapp-backup` and
   `webapp-shopify`, and the Tools workflow shows a test step.
3. Add up the "Tests:" lines from the first command above → the total is at least section 1's 902 Jest
   tests (more if tests were added), with 0 failed.
4. `pnpm nx run backend:test` ends with `0 failed`; check `git status` afterwards and don't commit the
   quote rewrites `black` makes in upstream files.

---

## 9. Follow-up work, not in this plan

- **Shopify walkthrough** in `docs/superpowers/specs/`, like
  [`2026-10-01-payfast-walkthrough.md`](../specs/2026-10-01-payfast-walkthrough.md): diagrams, setup and
  installation instructions. Tracked as step 13 of the
  [Shopify plan](2026-10-03-shopify-app-installation-plan.md).
- **Shopify component tests** (Shopify plan step 9) and **products page** (Shopify plan step 11).
