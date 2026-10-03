# Security fixes plan

Known security weaknesses in this repository, what each one risks, and how to fix it. Each item is fixed
test-first (RED before GREEN), like the rest of the codebase
([`docs/superpowers/agents.md`](../agents.md)). The human maintainer picks the order and approves each fix.

This repository is public, so items describe the weakness and the fix, never a working attack.

| #   | Weakness                                         | Risk   | Status                     |
| --- | ------------------------------------------------ | ------ | -------------------------- |
| 1   | Access tokens last 60 minutes and survive logout | Medium | Open (accepted 2026-10-02) |
| 2   | A public R2 bucket makes private files public    | Medium | Open                       |

---

## 1. Access tokens last 60 minutes and survive logout

**Found:** 2026-10-02, while debugging a logout after returning from the PayFast sandbox.

### What changed

`ACCESS_TOKEN_LIFETIME_MINUTES` was raised from the default of 5 to **60** in the untracked
`packages/backend/.env` and `packages/backend/.env.render`. It sets `SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]` in
[`config/settings.py`](../../../packages/backend/config/settings.py). The tracked templates
([`.env.shared`](../../../packages/backend/.env.shared)) still say 5.

### Why it was raised

PayFast sends the buyer back to the web app as a full page load. By then the access token was often older
than 5 minutes: it's issued at login or at the last renewal, and it's renewed only after a request fails. So
the 5 minutes count from that issue time, not from when the payment starts. An expired token in the `token`
cookie isn't refused; it's treated as "not logged in"
(`JSONWebTokenCookieAuthentication.authenticate` in
[`apps/users/authentication.py`](../../../packages/backend/apps/users/authentication.py) returns `None`). So the
web app never tries to renew the login and shows the login page. Only an expired token sent in the
`Authorization` header gets the 401 that makes the web app renew it
([`apolloClient.ts`](../../../packages/webapp-libs/webapp-api-client/src/graphql/apolloClient.ts),
`refreshTokenLink`). Both are upstream code. A longer lifetime avoided changing it.

Seen in the sandbox: subscription checkout at 15:56, back in the app at 15:57:51, logged out. The return page
then kept polling, because its status query answered `permission_denied` (see the PayFast walkthrough,
[`2026-10-01-payfast-walkthrough.md`](../specs/2026-10-01-payfast-walkthrough.md)).

### The weakness

- **A leaked access token works for up to an hour.** The access token is a self-contained JWT
  (`rest_framework_simplejwt.tokens.AccessToken`); the backend keeps no record of it.
- **Logging out doesn't revoke it.** Logout blacklists only the refresh token (`LogoutSerializer` in
  [`apps/users/serializers.py`](../../../packages/backend/apps/users/serializers.py)). An access token copied
  before logout keeps working until it expires, now up to 60 minutes instead of 5.
- **It's also readable by page scripts.** Besides the `httpOnly` cookie, the web app keeps a copy in
  `localStorage` for browsers that block the cookie (`storeAuthTokens` in
  [`auth.utils.ts`](../../../packages/webapp-libs/webapp-api-client/src/api/auth/auth.utils.ts)). Any script
  running on the page, such as one injected through a cross-site scripting (XSS) bug or a compromised
  dependency, can read it. A longer lifetime makes such a theft worth more.

The refresh token (7 days, rotated and blacklisted after use) is unchanged.

### Fix options

1. **Make the PayFast return page renew the login itself, then lower the lifetime again** (recommended).
   In [`payfastReturn.component.tsx`](../../../packages/webapp-libs/webapp-finances/src/payfast/routes/payfastReturn.component.tsx),
   when the status query answers `permission_denied`, call the existing renew function (`auth.refreshToken()`)
   once and query again; if that fails, go to the login page with a redirect back. This is PayFast code only,
   about 15 lines plus a test. Then set `ACCESS_TOKEN_LIFETIME_MINUTES` back to 5 to 15 in `.env` and
   `.env.render`, and redeploy.
2. **Renew on load across the whole web app.** When the current-user query comes back empty, try the refresh
   token once before treating the user as logged out. This fixes every full-page return (PayFast, email links),
   but it changes upstream code
   ([`commonQuery.component.tsx`](../../../packages/webapp-libs/webapp-api-client/src/providers/commonQuery/commonQuery.component.tsx))
   and may conflict on upstream syncs.
3. **Revoke access tokens at logout.** Record the access token's `jti` on logout and refuse it in the
   authentication classes until it expires. This closes the logout gap at any lifetime, but it adds a database
   or cache lookup per request and changes upstream code. Worth doing only if a longer lifetime must stay.

### Tests (for option 1)

- Return page: a status query answering `permission_denied` triggers one renewal and a retry; a successful
  retry with `complete` shows the success toast; a failed renewal redirects to the login page with the return
  URL as `redirect`.
- Manual (sandbox): with `ACCESS_TOKEN_LIFETIME_MINUTES=1`, start a subscription checkout, wait two minutes on
  PayFast's page, pay; the return page confirms the payment without a login prompt.

### Until it's fixed

60 minutes is a common choice for apps like this, and the risk stays limited while there is no known XSS
bug. Keep dependencies updated, and lower the lifetime as soon as option 1 lands.

---

## 2. A public R2 bucket makes private files public

**Found:** 2026-10-03, while setting up Cloudflare R2 for local development.

### What happens

Public files such as avatars use unsigned links (`querystring_auth=False` in `PublicCloudflareR2Storage`,
[`common/storages.py`](../../../packages/backend/common/storages.py)). R2 serves unsigned requests only through a
bucket's public address (its `r2.dev` development URL or a connected domain), set as `R2_CUSTOM_DOMAIN`. So to show
avatars, the bucket's public access has to be switched on.

Public access applies to the **whole bucket**, and this app keeps every kind of file in one bucket
(`R2_BUCKET_NAME`): avatars under `public/`, but also documents (the default storage, `CloudflareR2Storage`) and
exports (`get_exports_storage`, under `exports/`). And once `R2_CUSTOM_DOMAIN` is set, `CloudflareR2Storage` builds
its links on that public domain too, without a signature or an expiry, so documents stop getting signed links.

### The weakness

- **Anyone with a file's link can open it,** for as long as it exists, including documents and exports that are
  meant to be private. Links contain a random 16-character hex folder (`UniqueFilePathGenerator`), so they are hard
  to guess, but a link that is forwarded, logged or leaked stays valid forever.
- **Signed, expiring links are lost for private files** as soon as the public domain is set.

### Fix options

1. **Two buckets** (recommended): a public bucket, with public access on, for avatars and other public assets only;
   a private bucket, with public access off, for documents and exports, which keep signed, expiring links on the
   R2 endpoint. Needs a second bucket setting for the private storages (for example `R2_PRIVATE_BUCKET_NAME`), read
   by `CloudflareR2Storage`, with a loader test, and `R2_CUSTOM_DOMAIN` used only by `PublicCloudflareR2Storage`.
   This changes upstream code in `common/storages.py` and `config/settings.py`.
2. **One private bucket, signed links everywhere:** keep public access off and make avatars use signed links too.
   Simpler, but avatar links expire, which defeats browser and CDN caching, and changes upstream behaviour.
3. **Accept it for now:** keep one public bucket while the app holds no sensitive files, and revisit before real
   users upload private documents.

### Tests (for option 1)

- `CloudflareR2Storage` uses the private bucket, has no custom domain and builds signed links, even when
  `R2_CUSTOM_DOMAIN` is set.
- `PublicCloudflareR2Storage` uses the public bucket and `R2_CUSTOM_DOMAIN`, with unsigned links.
- The new bucket setting is read from its environment variable, with a safe default (rule 2.3).

### Until it's fixed

Don't store sensitive files while the bucket is public. On Render, check in the Cloudflare dashboard whether public
access is on for the production bucket; if no avatar is needed yet, leave it off.
