# PayFast Payment Backend — Implementation Plan

**Date:** 2026-09-30
**Status:** Implemented on branch `feat/payfast-payment-backend` (section 10); awaiting human checks (section 11) and the sandbox run (step 9)
**Goal:** Add PayFast as a second payment provider, selected with `PAYMENT_BACKEND=stripe|payfast`.
Stripe code is not deleted, and with `PAYMENT_BACKEND=stripe` the app behaves exactly as it did before. Since
2026-10-01 the default is `payfast` (decision 5 in section 9); this plan was written when it was `stripe`.

---

## 0. Feasibility and approach

**Yes, this is possible.** Stripe code lives almost entirely in `apps/finances` (backend) and
`webapp-libs/webapp-finances` (frontend). Only a few places outside those need to know which provider
is active:

| Touchpoint                           | File                                                                                                                                                                                                                           | Why it matters                                                           |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| Free plan on tenant creation         | [`apps/finances/signals.py`](../../../packages/backend/apps/finances/signals.py)                                                                                                                                               | Calls Stripe `initialize_tenant` on every new tenant                     |
| Tenant deletion cancels subscription | `apps/multitenancy/schema.py:379`                                                                                                                                                                                              | Calls Stripe `get_schedule` + `CancelTenantActiveSubscriptionSerializer` |
| GraphQL root                         | [`config/schema.py`](../../../packages/backend/config/schema.py)                                                                                                                                                               | Composes `finances_schema.Query/Mutation`                                |
| Finances routes                      | [`webapp-finances/src/routes/index.tsx`](../../../packages/webapp-libs/webapp-finances/src/routes/index.tsx)                                                                                                                   | Loads the Stripe-shaped subscription pages                               |
| Stripe.js client                     | [`webapp-core/src/config/env.ts`](../../../packages/webapp-libs/webapp-core/src/config/env.ts), [`webapp-finances/src/services/stripe/client.ts`](../../../packages/webapp-libs/webapp-finances/src/services/stripe/client.ts) | Needs a publishable key                                                  |

**Approach: two stacks side by side, with one small switch in the middle.** Stripe and PayFast work too
differently to share one interface. Stripe uses a client-side Elements SDK and a rich subscription-schedule
API. PayFast redirects to a hosted page and reports back through ITN. A shared abstraction would leak. So we:

1. Put PayFast in its **own Django app** (`apps.payfast`) with its own models, migrations, services, ITN view
   and GraphQL types. Nothing in `apps/finances` gets rewritten.
2. Add a thin **dispatch module** ([`apps/finances/billing.py`](../../../packages/backend/apps/finances/billing.py)) that the cross-cutting callers above use
   instead of calling Stripe services directly. With `stripe` it calls the same Stripe functions as today.
3. On the frontend, pick Stripe or PayFast **route components** based on a runtime `paymentConfig` query.

### Corrections to the previous draft of this file

An earlier draft existed at this path. Its structure was reasonable, but a few of its choices would fail
in this codebase. The fixes are built into this plan:

| Earlier draft                                                                                                                  | Problem                                                                                                                                                                                                                                                                                   | This plan                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Swap `Query`/`Mutation` classes in [`config/schema.py`](../../../packages/backend/config/schema.py) based on `PAYMENT_BACKEND` | The frontend's types are generated from a **committed** [`webapp-api-client/graphql/schema/api.graphql`](../../../packages/webapp-libs/webapp-api-client/graphql/schema/api.graphql). Swapping schemas at runtime breaks codegen and makes the Stripe UI fail type-checking under PayFast | Schema is **always the union** of both. Only resolver behaviour depends on the backend          |
| PayFast models in `apps/finances/payfast/models.py` with `app_label="finances"` and a `payfast/migrations/` folder             | Django doesn't discover models in a subpackage unless something imports them, and migrations for `app_label="finances"` must live in `apps/finances/migrations`. Mixing them into the Stripe app's migration history is fragile                                                           | Separate `apps.payfast` app, always installed, with its own migrations                          |
| `PAYFAST_*` settings defined only `if PAYMENT_BACKEND == "payfast"`                                                            | Importing any PayFast module under `stripe` raises `AttributeError`, and tests can't `override_settings` cleanly                                                                                                                                                                          | Always define settings; validate them with a system check when `payfast` is active              |
| Plan change = cancel + new checkout                                                                                            | Makes the customer re-enter card details for a monthly↔yearly switch                                                                                                                                                                                                                      | Use the Subscriptions API `update` endpoint (amount/frequency/run_date) on the existing token   |
| ITN source check via `Referer` header (copied from the Flask app)                                                              | PayFast doesn't reliably send `Referer`, and headers can be spoofed                                                                                                                                                                                                                       | Check the resolved client IP against IPs resolved from PayFast hostnames                        |
| Trust `custom_str2` (tenant id) from the ITN                                                                                   | Anyone can put any value in a checkout form field                                                                                                                                                                                                                                         | Look up tenant and expected amount from **our** pending checkout record keyed by `m_payment_id` |

A copy of that draft is in the session scratchpad, in case you want to compare.

---

## 1. PayFast facts we rely on (verified against the docs)

Read in full on 2026-09-30 from the PayFast developer docs (https://developers.payfast.co.za/docs) and API
reference (https://developers.payfast.co.za/api). Where the docs are silent, the item says so. Nothing
below is from memory. The working Flask integration
(`python-flask-whatsapp-store/app/payments/payfast.py`) is a secondary reference only.

### 1.1 Checkout (once-off and subscription)

Docs: https://developers.payfast.co.za/docs#step_1_form_fields and https://developers.payfast.co.za/docs#step_3_pay_on_payfast

- The browser POSTs an HTML form to `https://www.payfast.co.za/eng/process`
  (sandbox: `https://sandbox.payfast.co.za/eng/process`).
- Field groups, in documented order:
  - Merchant details: `merchant_id, merchant_key, return_url, cancel_url, notify_url, fica_idnumber`
  - Customer details: `name_first, name_last, email_address, cell_number`
  - Transaction details: `m_payment_id` (≤100 chars), `amount` (ZAR decimal, required), `item_name`
    (≤100, required), `item_description` (≤255), `custom_int1..5`, `custom_str1..5` (≤255)
  - Transaction options: `email_confirmation, confirmation_address`
  - Payment methods: `payment_method` (e.g. `cc`)
- `notify_url` sent with the transaction overrides the one set on the account.
- **Minimum amount:** "you will not be able to process payments with an amount less than ZAR 5.00"
  (https://developers.payfast.co.za/docs#go_live). The only exception is the R0 initial amount for
  subscriptions (section 1.2). So the system check rejects `PAYFAST_MONTHLY_PRICE`, `PAYFAST_YEARLY_PRICE` and any
  `PAYFAST_DONATION_AMOUNTS` value below 5.00.
- Test transactions made on the **live** account "will be subject to the agreed transaction fees which
  can unfortunately not be refunded" (same section).

### 1.2 Subscriptions (recurring billing, `subscription_type=1`)

Docs: https://developers.payfast.co.za/docs#recurring_billing and https://developers.payfast.co.za/docs#subscriptions

- These are the same checkout fields, plus the following. The attribute table lists them in this order:
  - `subscription_type` = `1` (required)
  - `billing_date`: "The date from which future subscription payments will be made… Defaults to current date if not set."
  - `recurring_amount`: "Future recurring amount… Defaults to the ‘amount’ value if not set. There is a
    minimum value of 5.00."
  - `frequency`: `1` Daily, `2` Weekly, `3` Monthly, `4` Quarterly, `5` Biannually, `6` Annual (required)
  - `cycles`: `0` = indefinite (required)
  - `subscription_notify_email`, `subscription_notify_webhook`, `subscription_notify_buyer` (booleans, below)
- **R0 initial amount (trial) — confirmed in the docs.** "It is possible to set up a subscription or
  tokenization payment with an initial amount of R0.00. This would be used with subscriptions if the first
  cycle/period is free… the customer will be redirected to Payfast, where they will input their credit card
  details and go through 3D Secure, but no money will be deducted." So a trial checkout is `amount=0.00`,
  `recurring_amount=<price>` and `billing_date=<today + SUBSCRIPTION_TRIAL_PERIOD_DAYS>`.
- **Trial and price-increase notices.** The docs say each of the three `subscription_notify_*` flags sends a
  notice "7 days before a subscription trial ends, or before a subscription amount increases":
  `subscription_notify_email` emails the merchant, `subscription_notify_webhook` sends a webhook, and
  `subscription_notify_buyer` emails the buyer. The email flags default to on through the dashboard.
  We send our own `TrialExpiresSoonEmail`, as Stripe does, so we post `subscription_notify_buyer=false`
  to avoid the buyer getting two emails. The webhook's payload is `type` = `subscription.free-trial` |
  `subscription.promo` | `subscription.update`, with `token, initial_amount, amount (cents), next_run,
frequency, …`. It goes to a URL set in the dashboard, and we don't need it.
- **Token.** "On successful payment completion and all subsequent recurring payments you will be sent a
  notification… A ‘token’ parameter will be sent as part of the notification and is to be used for all
  further API calls related to the subscription." (https://developers.payfast.co.za/docs#recurring_billing)
  The sandbox doesn't display the token, so "be sure to capture this from the ITN"
  (https://developers.payfast.co.za/docs#sandbox).
- **Failed recurring payments — there is no failure ITN.** "On failed payments, Payfast will try a number of
  times to reprocess a payment… On failure, the customer will be notified… On a complete failure (after X
  amount of times), the subscription will be ‘locked’ and will need some action from the merchant."
  (https://developers.payfast.co.za/docs#recurring_billing). The ITN `payment_status` is documented as only
  `COMPLETE` or `CANCELLED` (section 1.4). So we detect failure by **polling**: an expected renewal ITN that hasn't
  arrived, followed by `GET /subscriptions/:token/fetch` (section 1.5). Section 2 and section 3.2 are designed around this.
- **Docs are silent on:** whether a R0 trial checkout sends an ITN straight away (we need one to capture the
  token), and what `m_payment_id` recurring ITNs carry. Both are sandbox checks in step 9. Recurring
  ITNs are matched by `token` first, so the `m_payment_id` behaviour doesn't affect correctness.

### 1.3 Checkout signature

Docs: https://developers.payfast.co.za/docs#step_2_signature

- Concatenate "all the non-blank variables", as `key=value` joined by `&`. "The pairs must be listed in the
  **order in which they appear in the attributes description**… Do not use the API signature format, which
  uses alphabetical ordering!"
- Append `&passphrase=<passphrase>`. "The resultant URL encoding must be in upper case (eg. http%3A%2F%2F),
  and spaces encoded as ‘+’." Python's `urllib.parse.quote_plus` does exactly this. Then MD5, lower-case hex.
- Our full order is section 1.1's field groups followed by section 1.2's subscription fields, in their table order:
  `merchant_id, merchant_key, return_url, cancel_url, notify_url, fica_idnumber, name_first, name_last,
email_address, cell_number, m_payment_id, amount, item_name, item_description, custom_int1..5,
custom_str1..5, email_confirmation, confirmation_address, payment_method, subscription_type, billing_date,
recurring_amount, frequency, cycles, subscription_notify_email, subscription_notify_webhook,
subscription_notify_buyer`.
  The docs state the ordering rule and each section's table order. They don't print one combined list,
  so step 2's test vector is generated with the sandbox's signature tool ("Test your integration",
  https://developers.payfast.co.za/docs#sandbox) for a full subscription payload.
- ⚠️ The Flask `CHECKOUT_SIGNATURE_FIELD_ORDER` stops at `confirmation_address` and puts other fields at
  the end in dict order. That works for once-off payments but **would break for `custom_*` and all
  subscription fields**. The port must use the full order above.
- The passphrase is required for all subscriptions and API calls
  (https://developers.payfast.co.za/docs#sandbox). Set it in the sandbox under SETTINGS → "Salt Passphrase".
  The docs' examples use sandbox merchant `10000100`, key `46f0cd694581a` and passphrase `jt7NOE43FZPn`.

### 1.4 ITN (Instant Transaction Notification)

Docs: https://developers.payfast.co.za/docs#step_4_confirm_payment

- PayFast POSTs to `notify_url` **before** sending the buyer to `return_url`. "Return a header 200 to prevent
  further retries. If no 200 response is returned the notification will be re-sent immediately, then after
  10 minutes and then at exponentially longer intervals until eventually stopping." The sandbox "will only
  send payment notifications once" (https://developers.payfast.co.za/docs#sandbox).
- Fields: `m_payment_id, pf_payment_id, payment_status` (**`COMPLETE` / `CANCELLED` only**: "After a
  successful payment the status sent will be COMPLETE. When a subscription is cancelled the status will be
  CANCELLED."), `item_name, item_description, amount_gross, amount_fee, amount_net, custom_int1..5,
custom_str1..5, name_first, name_last, email_address, merchant_id`, then recurring fields `token` and
  `billing_date`, then `signature`.
- **The four security checks.** The docs say "you should not continue the process if a test fails":
  1. **Signature.** Build the parameter string from **all posted fields in the order received**, stopping at
     `signature`. Unlike checkout, **empty values are included**, because the docs' PHP loop url-encodes
     every posted value. Append the passphrase, then MD5.
  2. **Source.** The docs list the valid hosts as `www.payfast.co.za, w1w.payfast.co.za, w2w.payfast.co.za,
sandbox.payfast.co.za`, and their samples resolve these hosts and compare the result to the request
     IP (the Node sample reads `x-forwarded-for`). The published server IPs
     (https://developers.payfast.co.za/docs#ports-ips) are `197.97.145.144/28`, `41.74.179.192/27`,
     `102.216.36.0/28`, `102.216.36.128/28` and `144.126.193.139`. ITNs use ports 80, 8080, 8081 and 443
     only. We accept the request IP if it matches either the resolved hosts or these ranges, so a DNS
     failure doesn't reject a real ITN.
  3. **Amount.** Check `abs(expected - amount_gross) <= 0.01`.
  4. **Server confirmation.** POST the same parameter string to `https://www.payfast.co.za/eng/query/validate`
     (sandbox `https://sandbox.payfast.co.za/eng/query/validate`), and expect the body `VALID`. The docs'
     samples post the parameter string **without** the passphrase. The Flask code appends it, so don't copy
     that.

### 1.5 Subscriptions API

Docs: https://developers.payfast.co.za/api#recurring-billing and https://developers.payfast.co.za/api#authentication

- Base URL: `https://api.payfast.co.za/subscriptions/[token]/[action]`. Sandbox uses the same host with
  `?testing=true`.
- Headers on every call: `merchant-id`, `version: v1`, `timestamp` (ISO-8601, e.g.
  `2020-04-01T12:00:01+02:00`; with no offset, GMT+2 is assumed), and `signature`.
- API signature (https://developers.payfast.co.za/api#authentication):
  1. Sort all header, body and query variables **plus the passphrase** alphabetically. "When in test mode
     the testing parameter should be excluded from the signature."
  2. Concatenate the non-empty values, URL-encoded.
  3. MD5, lower case.
- Error codes (https://developers.payfast.co.za/api#errors): `401 Merchant authorisation failed` means a bad
  signature, and `429` is the signature rate limit. There's an optional IP whitelist for API callers
  (dashboard → Recurring Billing). If it's enabled, the backend's outbound IPs must be on it.
- Endpoints:
  - `GET /subscriptions/:token/fetch` (https://developers.payfast.co.za/api#subscription-object-fetch).
    Returns `amount` (cents), `cycles, cycles_complete, frequency, run_date, status, status_reason,
status_text`. Only `status: 1` / `"ACTIVE"` is documented, so any other value is treated as "needs
    attention" and logged with `status_reason`.
  - `PUT /subscriptions/:token/pause`, with optional `cycles` (default 1)
    (https://developers.payfast.co.za/api#pause-a-subscription)
  - `PUT /subscriptions/:token/unpause` (https://developers.payfast.co.za/api#unpause-a-subscription)
  - `PUT /subscriptions/:token/cancel` (https://developers.payfast.co.za/api#cancel-a-subscription). "This
    will cancel a subscription entirely. When a subscription is cancelled the customer will be notified of
    this via email." This triggers a `CANCELLED` ITN.
  - `PATCH /subscriptions/:token/update` (https://developers.payfast.co.za/api#update-a-subscription).
    Body is any of `cycles`, `frequency` (1–6), `run_date` (YYYY-MM-DD) and `amount` (**cents**), with at
    least one required. This **confirms plan changes can happen without a new checkout**.
  - `POST /subscriptions/:token/adhoc` (https://developers.payfast.co.za/api#create-an-ad-hoc-subscription).
    For tokenization only; not used.

### 1.6 Card update

Docs: https://developers.payfast.co.za/docs#recurring_card_update

- `GET https://www.payfast.co.za/eng/recurring/update/{token}?return={url}`. If `return` is omitted, "there
  will be no redirect". This works for subscriptions and tokenization.
- The docs give only the `www` host. PayFast's official PHP SDK groups card update with "onsite" features,
  which "error in sandbox" (https://github.com/Payfast/payfast-php-sdk#readme). So **card update can't be
  exercised in the sandbox**. It's covered by a unit test on the URL we generate, plus one live check.

### 1.7 Refunds API

Docs: https://developers.payfast.co.za/api#refunds

- `GET /refunds/query/:pf_payment_id` (https://developers.payfast.co.za/api#refund-query). Returns
  `amount_original, amount_available_for_refund, status` (`REFUNDABLE | COMPLETED | NOT_AVAILABLE`),
  `errors[]`, and `refund_full.method` / `refund_partial.method`
  (`PAYMENT_SOURCE | BANK_PAYOUT | NOT_AVAILABLE`), plus `bank_names[]`. PayFast "highly recommend"
  running this before any refund.
- `POST /refunds/:pf_payment_id` (https://developers.payfast.co.za/api#refund-create). Body: `amount`
  (cents, full or partial), `reason` (3–255 chars), `notify_buyer`, `notify_merchant`. For `BANK_PAYOUT`, it
  also needs `bank_account_holder, bank_name, bank_branch_code, bank_account_number, bank_account_type`.
- `GET /refunds/:pf_payment_id` (https://developers.payfast.co.za/api#refund-retrieve) returns the balance
  and refund transactions.
- **Sandbox: not supported.** The Refunds section, unlike Subscriptions, gives no sandbox URL. PayFast's
  PHP SDK README says refunds need `testMode = false`, otherwise it throws "Sorry but Onsite is not
  available in Sandbox mode" (https://github.com/Payfast/payfast-php-sdk#refunds). Refunds are therefore
  tested with mocked unit tests and one small **live** refund. That costs fees, which aren't refundable
  (section 1.1).

### 1.8 Tokenization (`subscription_type=2`) — not used

Docs: https://developers.payfast.co.za/docs#tokenization. "Payfast will only charge the customer's card when
instructed to do so via the API." Using it would mean running our own billing scheduler, so plans use
subscriptions (section 1.2).

## 2. Target behaviour (parity with the Stripe flow)

The Stripe implementation has one active **subscription schedule** per tenant, with plans `free_plan`,
`monthly_plan` and `yearly_plan` ([`apps/finances/constants.py`](../../../packages/backend/apps/finances/constants.py)). A plan change takes effect in the **next
phase**, meaning at the end of the current period. A trial of `SUBSCRIPTION_TRIAL_PERIOD_DAYS` (7) is
granted once per customer. Cancelling ends at period end.

**Guiding rule (agreed): PayFast behaves like the Stripe implementation wherever both APIs allow it.** That
means the same plan names, the same `SUBSCRIPTION_TRIAL_PERIOD_DAYS` setting, the same once-per-tenant trial
rule, plan changes at period end, the same emails, and the same donation page. When PayFast can't do
something, the table says so and names the closest equivalent.

| Action                                                | Stripe (today, unchanged)                                                                                                   | PayFast (new)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tenant created                                        | Schedule on free plan (Stripe API)                                                                                          | Local `PayFastSubscription(plan=free_plan, status=active)`, no PayFast call                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| Free → paid                                           | `changeActiveSubscription` with a price and a stored card                                                                   | `payfastCreateCheckout(plan)` returns form fields; the browser POSTs to PayFast; the ITN activates the subscription and stores the `token`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| Paid → other paid (monthly↔yearly)                    | Next schedule phase                                                                                                         | `PATCH /update` with the new `amount` + `frequency`, `run_date` = current period end; record `pending_plan` locally and apply it on the next ITN                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Cancel (paid → free)                                  | Schedule ends at period end                                                                                                 | `PUT /cancel` straight away (stops future charges); locally `cancel_at_period_end=True`; the effective plan stays paid until `current_period_end`, then free                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Trial                                                 | Trial phase once per customer (`utils.customer_can_activate_trial`); a card is still required                               | Same rule (`has_used_trial` on the tenant's subscription) and the same `SUBSCRIPTION_TRIAL_PERIOD_DAYS`. Checkout with initial `amount=0.00`, `billing_date=today+trial_days`, `recurring_amount=price`, so the card is captured at checkout (with 3-D Secure) and nothing is charged, as with Stripe. R0 initial amounts are explicitly supported (section 1.2, https://developers.payfast.co.za/docs#subscriptions)                                                                                                                                                                                                                                                                                                                                   |
| Trial ending soon email                               | `customer.subscription.trial_will_end` webhook → `TrialExpiresSoonEmail`                                                    | PayFast's own notice is fixed at 7 days before trial end and goes to a dashboard-configured URL (section 1.2), which doesn't fit a 7-day trial. A daily Celery beat task sends the same `TrialExpiresSoonEmail` 3 days before `trial_end` (Stripe's lead time), once per trial (`trial_reminder_sent_at`). Checkout posts `subscription_notify_buyer=false`, so the buyer doesn't also get PayFast's email                                                                                                                                                                                                                                                                                                                                              |
| Recurring charge                                      | `invoice.*` webhooks                                                                                                        | ITN `COMPLETE` with the token: add a `PayFastPayment`, move the period forward                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| Payment failed                                        | `invoice.payment_failed`: cancel trial + send `SubscriptionErrorEmail`                                                      | **PayFast sends no failure ITN.** `payment_status` is only `COMPLETE`/`CANCELLED`; PayFast retries the charge itself, emails the buyer, and eventually "locks" the subscription (section 1.2, https://developers.payfast.co.za/docs#recurring_billing). The daily task finds subscriptions whose renewal ITN is overdue (`current_period_end` passed plus 1 day), calls `GET /fetch` (https://developers.payfast.co.za/api#subscription-object-fetch), and sets `past_due` if the run date hasn't moved forward or the status isn't `ACTIVE`. It sends `SubscriptionErrorEmail` once. If that subscription was the trial's first charge, it calls `PUT /cancel`, as the Stripe handler cancels a failed trial. A later `COMPLETE` ITN clears `past_due` |
| Payment methods page                                  | List/add/delete Stripe cards                                                                                                | "Card managed by PayFast" + an **Update card** button linking to `https://www.payfast.co.za/eng/recurring/update/{token}?return=…` (https://developers.payfast.co.za/docs#recurring_card_update). No list/delete: PayFast stores the card, and the API has no card listing. Not testable in the sandbox (section 1.6)                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Transaction history                                   | `allCharges`; entries without an invoice are labelled "Donation", others "{plan} plan"                                      | `payfastPayments` from our `PayFastPayment` rows, with the same labels (`kind=donation` → "Donation")                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Tenant deleted                                        | Cancel schedule                                                                                                             | `PUT /cancel` if a token exists                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **Donations** (once-off, `/finances/payment-confirm`) | `PaymentIntentSerializer`: choose 5/10/15 USD, pay with Stripe Elements on the page, toast "Payment successful" and go home | **In v1.** Same page, same fixed-amount radio picker, amounts from `PAYFAST_DONATION_AMOUNTS` (ZAR). "Pay R{amount}" calls `payfastCreateDonationCheckout(amount)`; the browser POSTs to PayFast (once-off, no `subscription_type`); the ITN records a `PayFastPayment(kind=donation)`; the return page shows the same success toast and goes home. Stripe's `setup_future_usage` (saving the card) has no PayFast equivalent for once-off payments, which is fine because donations don't reuse cards                                                                                                                                                                                                                                                  |
| Admin refund of a donation                            | `views_admin.py` + `AdminStripePaymentIntentRefundSerializer`                                                               | Same admin form (amount + reason) for a `PayFastPayment`. It calls `GET /refunds/query/:pf_payment_id` first, then `POST /refunds/:pf_payment_id` (https://developers.payfast.co.za/api#refund-query, https://developers.payfast.co.za/api#refund-create). If the query says `BANK_PAYOUT` (e.g. EFT payments), the form also asks for the bank fields. If it says `NOT_AVAILABLE`, the form shows PayFast's `errors[]`. **Refunds don't work in the sandbox** (section 1.7), so this step is covered by mocked unit tests plus one live refund                                                                                                                                                                                                         |

**Effective plan is computed on read**, so we don't need a scheduler to downgrade a cancelled subscription:
`paid if status in (active, trialing, past_due-within-grace) and (not cancel_at_period_end or now < current_period_end), else free`.
A daily Celery beat task (`payfast.daily_maintenance`) is **required**, since PayFast gives no event for
either case. It sends trial-ending emails, and it detects failed or locked renewals through `/fetch`.
The same `/fetch` pass also repairs missed ITNs. `CELERY_BEAT_SCHEDULE`
already exists in `config/settings.py:677`. Register the task there only when `PAYMENT_BACKEND == "payfast"`,
the same way the Contentful sync entry is added conditionally at line 700.

---

## 3. Backend design

### 3.1 Settings ([`config/settings.py`](../../../packages/backend/config/settings.py)) — additive only

```python
PAYMENT_BACKEND = env("PAYMENT_BACKEND", default="payfast")  # "payfast" | "stripe"
PAYMENT_BACKENDS = ("stripe", "payfast")

# existing Stripe block unchanged, except the final line:
STRIPE_ENABLED = PAYMENT_BACKEND == "stripe" and (
    "<CHANGE_ME>" not in STRIPE_LIVE_SECRET_KEY or "<CHANGE_ME>" not in STRIPE_TEST_SECRET_KEY
)

# Two credential sets (agreed 2026-09-30), chosen by ENVIRONMENT_NAME: "production" -> *_PRODUCTION on
# live PayFast; anything else -> *_DEVELOPMENT on the sandbox. The app only reads the resolved names.
PAYFAST_ENVIRONMENT = "production" if ENVIRONMENT_NAME == "production" else "development"
PAYFAST_SANDBOX = PAYFAST_ENVIRONMENT != "production"   # derived, no longer an env var
_PAYFAST_SUFFIX = PAYFAST_ENVIRONMENT.upper()
PAYFAST_MERCHANT_ID = env(f"PAYFAST_MERCHANT_ID_{_PAYFAST_SUFFIX}", default="")
PAYFAST_MERCHANT_KEY = env(f"PAYFAST_MERCHANT_KEY_{_PAYFAST_SUFFIX}", default="")
PAYFAST_PASSPHRASE = env(f"PAYFAST_PASSPHRASE_{_PAYFAST_SUFFIX}", default="")
PAYFAST_NOTIFY_URL = env(f"PAYFAST_NOTIFY_URL_{_PAYFAST_SUFFIX}", default="")  # public URL of the ITN view
PAYFAST_VERIFY_SOURCE_IP = env.bool("PAYFAST_VERIFY_SOURCE_IP", default=True)  # False only for local/ngrok
# Prices (ZAR). Env vars with code defaults; parsed to Decimal and validated (> 0, 2 dp) by the system check.
PAYFAST_MONTHLY_PRICE = env("PAYFAST_MONTHLY_PRICE", default="199.00")
PAYFAST_YEARLY_PRICE = env("PAYFAST_YEARLY_PRICE", default="1990.00")
# Donation amounts (ZAR), comma-separated; the counterpart of Stripe's 5/10/15 USD choices
PAYFAST_DONATION_AMOUNTS = env.list("PAYFAST_DONATION_AMOUNTS", default=["50", "100", "150"])
# Trial length is NOT a new setting: reuse the existing SUBSCRIPTION_TRIAL_PERIOD_DAYS (default 7)
```

[`apps/payfast/constants.py`](../../../packages/backend/apps/payfast/constants.py) builds a single lookup from these settings and the existing plan names, so the
plan identities stay shared with Stripe:

```python
from apps.finances import constants as finance_constants

def plan_prices() -> dict[str, PayFastPlan]:
    return {
        finance_constants.FREE_PLAN.name:    PayFastPlan(amount=Decimal("0.00"), frequency=None),
        finance_constants.MONTHLY_PLAN.name: PayFastPlan(amount=Decimal(settings.PAYFAST_MONTHLY_PRICE), frequency=Frequency.MONTHLY),
        finance_constants.YEARLY_PLAN.name:  PayFastPlan(amount=Decimal(settings.PAYFAST_YEARLY_PRICE),  frequency=Frequency.ANNUAL),
    }
```

This is a function, not a module-level constant, so `override_settings` in tests picks up changes.
**Prices are snapshotted** on `PayFastCheckout` and `PayFastSubscription.amount` at checkout time. If you
later change the env var, existing subscribers keep their price until their plan changes (Stripe behaves
the same way, since prices are immutable). ITN amount checks compare against the snapshot, not the current env value.

- `return_url`/`cancel_url` are built from the existing `WEB_APP_URL` setting (`config/settings.py:639`),
  so they need no new env vars.
- If `PAYMENT_BACKEND` is `stripe`, `STRIPE_ENABLED` is computed exactly as today.
- When `payfast` is active, also silence `djstripe.C001/I001/I002` (same list as `STRIPE_CHECKS_ENABLED=False`).
- `djstripe` stays in `INSTALLED_APPS`, and `apps.payfast` is added unconditionally. Both sets of tables
  always exist, so switching backends never needs different migrations.

**System check** ([`apps/payfast/checks.py`](../../../packages/backend/apps/payfast/checks.py)): an error if `PAYMENT_BACKEND` isn't in `PAYMENT_BACKENDS`.
When it is `payfast`, also an error if merchant id, key, passphrase or notify URL are empty (the
passphrase is mandatory for subscriptions and the API, section 1.3), or if any price or donation amount is below
R5.00 (PayFast's minimum, section 1.1).

### 3.2 New app [`packages/backend/apps/payfast/`](../../../packages/backend/apps/payfast/)

```
apps/payfast/
├── __init__.py
├── apps.py              # PayfastConfig.ready(): register checks
├── checks.py
├── constants.py         # Frequency enum, hosts, PAYFAST_PLAN_PRICES (plan name -> Decimal, frequency)
├── models.py
├── admin.py             # read-only admin for the three models
├── migrations/0001_initial.py
├── signature.py         # checkout_signature(), itn_param_string(), api_signature() — pure functions
├── client.py            # PayFastApiClient: fetch/cancel/pause/unpause/update (requests, 10s timeout)
├── itn.py               # validate_itn(request) -> ValidatedItn | raises ItnError
├── services.py          # initialize_tenant, create_checkout, change_plan, cancel, handle_itn, effective_plan
├── views.py             # payfast_itn_view (csrf_exempt, POST only)
├── urls.py              # path("notify/", ...)
├── schema.py            # GraphQL types, queries, mutations
├── tasks.py             # reconcile_subscriptions (optional)
└── tests/
```

**Models** (all tenant-scoped, ZAR amounts as `Decimal`):

```python
class PayFastSubscription(TimeStampedModel):
    tenant = OneToOneField("multitenancy.Tenant", on_delete=CASCADE, related_name="payfast_subscription")
    plan = CharField(max_length=32, default=constants.FREE_PLAN.name)   # free_plan|monthly_plan|yearly_plan
    pending_plan = CharField(max_length=32, blank=True)                 # applied at next charge
    status = CharField(choices=Status.choices, default=Status.ACTIVE)   # active|trialing|past_due|cancelled
    token = CharField(max_length=64, blank=True, db_index=True)         # PayFast subscription token
    amount = DecimalField(max_digits=10, decimal_places=2, default=0)
    frequency = PositiveSmallIntegerField(null=True)
    current_period_start = DateTimeField(null=True)
    current_period_end = DateTimeField(null=True)
    trial_end = DateTimeField(null=True)
    has_used_trial = BooleanField(default=False)                        # parity with customer_can_activate_trial
    trial_reminder_sent_at = DateTimeField(null=True)                   # TrialExpiresSoonEmail sent once
    cancel_at_period_end = BooleanField(default=False)

    @property
    def subscriber(self):  # lets us reuse apps.finances.notifications.CustomerEmail unchanged
        return self.tenant

class PayFastCheckout(TimeStampedModel):
    """A checkout we started. The source of truth for tenant, plan and expected amount when the ITN arrives."""
    m_payment_id = UUIDField(unique=True, default=uuid4)
    kind = CharField(choices=subscription|donation)
    tenant = ForeignKey("multitenancy.Tenant", on_delete=CASCADE)
    created_by = ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=SET_NULL)
    plan = CharField(max_length=32, blank=True)   # empty for donations
    amount = DecimalField(...)                    # initial amount (0 for trial; the donation amount)
    recurring_amount = DecimalField(null=True)    # null for donations
    is_trial = BooleanField(default=False)
    status = CharField(choices=pending|complete|failed|cancelled)

class PayFastPayment(TimeStampedModel):
    """One ITN-confirmed transaction (initial or recurring). Shown in transaction history."""
    tenant = ForeignKey(...)
    kind = CharField(choices=subscription|donation)         # drives the "Donation" / "{plan} plan" label
    subscription = ForeignKey(PayFastSubscription, null=True, on_delete=SET_NULL)  # null for donations
    plan = CharField(max_length=32, blank=True)             # plan this charge paid for (history label)
    refunded_amount = DecimalField(default=0)               # admin refunds (step 8b)
    pf_payment_id = CharField(max_length=64, unique=True)   # idempotency key
    m_payment_id = CharField(max_length=64, db_index=True)
    amount_gross = DecimalField(...); amount_fee = DecimalField(...); amount_net = DecimalField(...)
    payment_status = CharField(max_length=16)
    item_name = CharField(max_length=255)
    raw = JSONField()                                       # full ITN payload for audit
```

`PayFastSubscription` is created for **every** tenant when `payfast` is active. It's the counterpart of
the free-plan schedule. A data migration or management command (`payfast_init_tenants`) backfills
existing tenants when you switch an existing deployment to PayFast.

**Signature module:** port from `payfast.py` as pure functions with no Flask or Django state, so it's easy
to unit-test:

- `checkout_signature(fields: dict, passphrase) -> str`: full documented order (section 1.3), blanks skipped,
  `quote_plus`. See https://developers.payfast.co.za/docs#step_2_signature
- `itn_param_string(raw_body: bytes) -> str` and `itn_signature_valid(...)`: received order, **blanks
  included**, stops at `signature` (section 1.4). Parse `request.body` directly, since `QueryDict` doesn't promise to
  keep order. See https://developers.payfast.co.za/docs#step_4_confirm_payment
- `api_signature(headers: dict, body: dict, passphrase) -> str`: alphabetical, passphrase included in the
  sort, `testing` excluded (section 1.5). See https://developers.payfast.co.za/api#authentication

**ITN view** ([`views.py`](../../../packages/backend/apps/payfast/views.py)), inside `transaction.atomic()`:

1. Reject anything that isn't a POST.
2. `validate_itn` runs the four checks from https://developers.payfast.co.za/docs#step_4_confirm_payment:
   signature → source → amount (step 4 below) → server `/eng/query/validate`, which is posted without the
   passphrase.
   - **Source:** the IP must be in the resolved PayFast hosts or the published ranges
     (https://developers.payfast.co.za/docs#ports-ips).
   - **Proxies:** behind Render or the AWS ALB, the client IP comes from `X-Forwarded-For`. Reuse whatever
     the project's proxy settings already trust.
   - Skip the IP check only if `PAYFAST_VERIFY_SOURCE_IP=False`, and never based on the environment name.
3. Find `PayFastCheckout` by `m_payment_id` (`select_for_update`). If the ITN carries a `token` for a known
   subscription, find the subscription instead.
4. Compare `amount_gross` to the **expected** amount: `checkout.amount` for the first ITN, or
   `subscription.amount` (or the pending plan's amount) for recurring ones.
5. Idempotency: if a `PayFastPayment` with this `pf_payment_id` already exists, return 200 without doing anything.
6. `services.handle_itn(...)`:
   - `COMPLETE` on a **donation** checkout: save `PayFastPayment(kind=donation)`, set
     `checkout.status=complete`. Nothing else changes.
   - `COMPLETE` on a first subscription checkout: set plan, token, amount and frequency, `status=trialing|active`,
     set the period dates, `checkout.status=complete`.
   - `COMPLETE` on a recurring charge: apply `pending_plan`, move the period forward by the frequency,
     set `status=active`, save a `PayFastPayment`.
   - There is no `FAILED` status (section 1.4). Failures are handled by the daily task (section 2).
   - `CANCELLED`: set `cancel_at_period_end=True` (or `cancelled` if already past the period end).
7. Return `200 OK` once the ITN has been processed, or when it's a duplicate. Return 400 if validation
   fails. Any non-200 makes PayFast retry: immediately, after 10 minutes, then with backoff (section 1.4). Log everything except the passphrase.

Only the ITN changes subscription state. `return_url` is only for UX.

**URLs:** [`config/urls_api.py`](../../../packages/backend/config/urls_api.py) gets `path("payfast/", include("apps.payfast.urls"))`, which gives
`/api/payfast/notify/`. It's always routed. When `payfast` isn't active, the view returns 404, so a stray
ITN can't change state.

### 3.3 Dispatch module [`apps/finances/billing.py`](../../../packages/backend/apps/finances/billing.py) (new)

This is the only new code in `apps/finances`. Cross-cutting callers use it, and Stripe services aren't changed.

```python
def is_payfast() -> bool: return settings.PAYMENT_BACKEND == "payfast"

def initialize_tenant(tenant):
    if is_payfast():
        return payfast_services.initialize_tenant(tenant)
    return subscriptions.initialize_tenant(tenant=tenant)          # existing Stripe function

def cancel_tenant_subscription(tenant):
    if is_payfast():
        return payfast_services.cancel(tenant, immediate=True)
    schedule = subscriptions.get_schedule(tenant)                  # existing lines moved here verbatim
    if schedule:
        s = CancelTenantActiveSubscriptionSerializer(instance=schedule, data={})
        if s.is_valid():
            s.save()
```

**Edits to existing files** (small, behaviour-preserving under `stripe`):

| File                                                                             | Change                                                                                                                                                                                                                         |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [`apps/finances/signals.py`](../../../packages/backend/apps/finances/signals.py) | `if settings.PAYMENT_BACKEND == "payfast": billing.initialize_tenant(instance); return` added **before** the existing `STRIPE_ENABLED` guard. The Stripe branch is untouched                                                   |
| `apps/multitenancy/schema.py:378-386`                                            | Replace the inline Stripe cancel with `billing.cancel_tenant_subscription(tenant)`. Keep the existing `try/except` + warning                                                                                                   |
| [`config/schema.py`](../../../packages/backend/config/schema.py)                 | Add `payfast_schema.Query` / `payfast_schema.Mutation` to the composed lists, alongside `finances_schema`                                                                                                                      |
| [`config/urls_api.py`](../../../packages/backend/config/urls_api.py)             | Add the [`payfast/`](../../../packages/webapp-libs/webapp-finances/src/payfast/) include                                                                                                                                       |
| [`config/settings.py`](../../../packages/backend/config/settings.py)             | section 3.1                                                                                                                                                                                                                    |
| [`packages/backend/.env.shared`](../../../packages/backend/.env.shared)          | Commented PayFast block + `PAYMENT_BACKEND=payfast`                                                                                                                                                                            |
| [`apps/finances/schema.py`](../../../packages/backend/apps/finances/schema.py)   | **One** addition: a `payment_config` query field, since it is finances-wide. Could go in [`apps/payfast/schema.py`](../../../packages/backend/apps/payfast/schema.py) instead if you want `finances/schema.py` fully untouched |

[`apps/finances/apps.py`](../../../packages/backend/apps/finances/apps.py), `webhooks.py`, `services/*`, `serializers.py`, [`models.py`](../../../packages/backend/apps/payfast/models.py), `managers.py` and
[`urls.py`](../../../packages/backend/apps/payfast/urls.py) are **unchanged**. djstripe webhook handlers stay registered, but they only fire when Stripe
sends events, which it won't if you haven't configured it.

### 3.4 GraphQL API (always in the schema)

```graphql
type PaymentConfigType { backend: String!, currency: String!, stripePublishableKeyRequired: Boolean! }

type PayFastPlanType { name: String!, amount: Decimal!, currency: String!, interval: String! }  # "month"|"year"|null
type PayFastSubscriptionType {
  plan: String!, pendingPlan: String, status: String!, amount: Decimal!,
  currentPeriodStart: DateTime, currentPeriodEnd: DateTime, trialEnd: DateTime,
  cancelAtPeriodEnd: Boolean!, canActivateTrial: Boolean!, hasCard: Boolean!, cardUpdateUrl: String
}
type PayFastPaymentType implements Node { pfPaymentId, kind, plan, amountGross, refundedAmount, paymentStatus, itemName, created }
type PayFastCheckoutType { actionUrl: String!, fields: GenericScalar!, mPaymentId: ID! }

type Query {
  paymentConfig: PaymentConfigType!                                   # AnyoneFullAccess
  payfastSubscriptionPlans: [PayFastPlanType!]!                       # AnyoneFullAccess (prices from env)
  payfastDonationAmounts: [Decimal!]!                                 # AnyoneFullAccess (PAYFAST_DONATION_AMOUNTS)
  payfastCheckoutStatus(tenantId: ID!, mPaymentId: ID!): String       # billing.view — polled by return page
  payfastActiveSubscription(tenantId: ID!): PayFastSubscriptionType   # billing.view
  payfastPayments(tenantId: ID!, ...connection args): PayFastPaymentConnection  # billing.view
}
type Mutation {
  payfastCreateCheckout(input: {tenantId, plan}): PayFastCheckoutType                            # billing.manage
  payfastCreateDonationCheckout(input: {tenantId, amount}): PayFastCheckoutType                  # billing.manage (same ACL as createPaymentIntent)
  payfastChangePlan(input: {tenantId, plan}): { activeSubscription }                             # billing.manage
  payfastCancelSubscription(input: {tenantId}): { activeSubscription }                           # billing.manage
}
```

- `payfastCreateDonationCheckout` rejects any `amount` not in `PAYFAST_DONATION_AMOUNTS`, the same way
  `PaymentIntentSerializer.product` is a fixed `ChoiceField`. The client never chooses an arbitrary price.
- `payfastCreateCheckout` works out `is_trial` on the server (`not has_used_trial`) and sets
  `amount`/`billing_date` to match. The client can't request a trial.
- Use the same ACL decorators as [`apps/finances/schema.py`](../../../packages/backend/apps/finances/schema.py) (`IsTenantMemberAccess`, `requires("billing.view"|"billing.manage")`).
- Log actions with `log_action(... entity_type="subscription")`, matching the Stripe mutations.
- PayFast resolvers raise `GraphQlValidationError("PayFast is not the active payment backend")` when
  `stripe` is active. Stripe resolvers are left as they are.
- After the backend changes, regenerate the schema and types:
  `pnpm nx run webapp-api-client:graphql:download-schema` (downloads [`api.graphql`](../../../packages/webapp-libs/webapp-api-client/graphql/schema/api.graphql) and runs `generate-types`).
  Commit [`api.graphql`](../../../packages/webapp-libs/webapp-api-client/graphql/schema/api.graphql) and the `__generated` files together.

---

## 4. Frontend design (`packages/webapp-libs/webapp-finances`)

**The runtime config is the source of truth.** A new `usePaymentConfig()` hook queries `paymentConfig`
(cache-first), so one frontend build works with either backend. No `VITE_PAYMENT_BACKEND` is needed.
`VITE_STRIPE_PUBLISHABLE_KEY` can stay unset under PayFast. Check that [`services/stripe/client.ts`](../../../packages/webapp-libs/webapp-finances/src/services/stripe/client.ts) only
calls `loadStripe` lazily; if it runs at import time, wrap it so it doesn't run when the key is empty.

**Route-level switch:** [`routes/index.tsx`](../../../packages/webapp-libs/webapp-finances/src/routes/index.tsx) exports the same names. Each exported route becomes a small
switcher that lazy-loads either the existing Stripe component (unchanged) or the PayFast one:

```tsx
export const CurrentSubscriptionContent = paymentBackendSwitch({
  stripe: () => import('./subscriptions/subscriptions.content'),
  payfast: () => import('../payfast/routes/currentSubscription.content'),
});
```

The PayFast code lives in [`src/payfast/`](../../../packages/webapp-libs/webapp-finances/src/payfast/):

```
src/payfast/
├── payfast.graphql.ts                 # queries/mutations from section 3.4
├── usePaymentConfig.hook.ts
├── submitPayfastCheckout.ts           # builds a hidden <form method="POST" action={actionUrl}> and submits it
├── routes/
│   ├── currentSubscription.content.tsx  # plan, status, next billing date, "Change plan", "Cancel"
│   ├── editSubscription.component.tsx   # plan cards (ZAR); free→paid = checkout, paid→paid = changePlan
│   ├── cancelSubscription.component.tsx
│   ├── paymentMethod.content.tsx        # "Your card is stored securely by PayFast" + Update card link
│   ├── transactionsHistory.content.tsx  # payfastPayments list ("Donation" / "{plan} plan" labels)
│   ├── paymentConfirm.component.tsx     # donation page: same layout/copy structure as the Stripe
│   │                                     # PaymentConfirm, radio of payfastDonationAmounts, "Pay R{amount}"
│   └── payfastReturn.component.tsx      # "Confirming your payment…"; polls payfastCheckoutStatus(mPaymentId)
│                                         # every 2s for up to 60s until the ITN lands, then:
│                                         #   donation → home + "Payment successful" toast (as Stripe)
│                                         #   subscription → current subscription page + success toast
│                                         #   timeout → "We'll update this page when PayFast confirms"
└── __tests__/
```

- `PaymentConfirm` in [`routes/index.tsx`](../../../packages/webapp-libs/webapp-finances/src/routes/index.tsx) goes through the same switcher, so the existing sidebar and
  home-page links to `/finances/payment-confirm` work under both backends without changes.
- The checkout mutations build `return_url` as `{WEB_APP_URL}/.../payfast-return?m={m_payment_id}`
  and `cancel_url` back to the page the user came from.
- Add `subscriptions.payfastReturn: 'payfast-return'` to [`config/routes.ts`](../../../packages/webapp-libs/webapp-finances/src/config/routes.ts). Also register it in
  [`packages/webapp/src/app/app.component.tsx`](../../../packages/webapp/src/app/app.component.tsx) next to the existing finances routes.
- `activeSubscriptionContext` is Stripe-shaped, so PayFast pages use their own context and don't touch it.
- Money formatting: ZAR (`R 199.00`) through the existing i18n/`Intl` helpers.
- Add i18n strings (react-intl) for the new pages, then run the project's translation extraction.

---

## 5. Implementation steps (each step can be merged on its own)

Work on a feature branch off `master`, using Conventional Commits (e.g. `feat(payfast): ...`).
Verify each step with `pnpm nx run backend:lint`, `pnpm nx run backend:test`, and for the frontend
`pnpm nx run webapp-finances:lint|test|type-check`.

1. **Switch + settings, no behaviour change.** Add `PAYMENT_BACKEND`, PayFast settings, the system check,
   `apps.payfast` skeleton + migrations, and [`.env.shared`](../../../packages/backend/.env.shared) docs. _Test:_ the full existing suite passes
   untouched, and `manage.py check` fails with a clear message when `PAYMENT_BACKEND=payfast` without creds.
2. **Signature + API client.** [`signature.py`](../../../packages/backend/apps/payfast/signature.py) and [`client.py`](../../../packages/backend/apps/payfast/client.py). Unit tests use fixed vectors:
   - a full subscription payload signed with the sandbox's signature tool
     (https://developers.payfast.co.za/docs#sandbox)
   - the Flask app's known-good once-off case
   - `responses`/`requests-mock` for the API, with response bodies copied from
     https://developers.payfast.co.za/api#recurring-billing
3. **Models + services + dispatch.** `initialize_tenant`, `effective_plan`, `billing.py`, and the `signals.py`
   and `multitenancy/schema.py` edits. _Test:_ a tenant created under `payfast` gets a free
   `PayFastSubscription` and makes no Stripe calls; under `stripe`, the existing tests (which mock
   `initialize_tenant`) still pass.
4. **Checkout + ITN.** `create_checkout`, [`views.py`](../../../packages/backend/apps/payfast/views.py), [`itn.py`](../../../packages/backend/apps/payfast/itn.py), `handle_itn`. _Test:_ ITN view tests for
   valid, bad signature, bad IP, an ITN with empty fields (signature must still match), amount mismatch,
   duplicate `pf_payment_id`, unknown `m_payment_id`, CANCELLED, a recurring COMPLETE that applies
   `pending_plan`, a donation COMPLETE, and a trial checkout that expects R0. Mock the `/validate` call.
   Build fixtures from the documented ITN payload
   (https://developers.payfast.co.za/docs#step_4_confirm_payment).
5. **Plan change + cancel + tenant deletion.** `change_plan` (API update), `cancel`. _Test:_ API client
   calls are mocked, local state transitions are checked, and effective plan after period end is free.
   Also test trial parity: a second checkout after a trial was used is not a trial, and changing plan
   during a trial ends it (as `TenantSubscriptionScheduleSerializer` does for Stripe).
   5b. **Donations.** `create_donation_checkout` + `payfastDonationAmounts`. _Test:_ an amount outside
   `PAYFAST_DONATION_AMOUNTS` is rejected, and the ITN records `kind=donation` without touching the subscription.
6. **GraphQL.** section 3.4 plus schema regeneration. _Test:_ schema tests with ACL (member without
   `billing.manage` can't create a checkout) and the "not active backend" error.
7. **Frontend.** Config hook, route switcher, PayFast pages, return page. _Test:_ Jest/RTL tests with mocked
   Apollo for each page (including the PayFast donation page), and a switcher test showing Stripe components
   render when `backend=stripe`, for both the subscription routes and `PaymentConfirm`.
8. **Beat task + backfill.** `daily_maintenance` (required):
   - sends `TrialExpiresSoonEmail` 3 days before `trial_end`
   - calls `/fetch` on overdue renewals to set `past_due`, send `SubscriptionErrorEmail`, and cancel a
     failed first charge after a trial

   Also adds the `payfast_init_tenants` backfill command. _Test:_ frozen-time unit tests with the API mocked.
   8b. **Admin refund (parity with Stripe's admin refund view).** Query, then create, as section 2 describes.
   _Test:_ mocked unit tests for the `PAYMENT_SOURCE`, `BANK_PAYOUT` and `NOT_AVAILABLE` responses. The
   only real check is a live refund, because refunds don't work in the sandbox (section 1.7).

9. **Sandbox end-to-end.** Expose the backend with ngrok, set `PAYFAST_NOTIFY_URL` and
   `PAYFAST_VERIFY_SOURCE_IP=False` (ngrok hides the source IP), then run: subscribe monthly → ITN →
   trialing (R0) or active; switch to yearly; cancel; make a R50 donation. Record in this plan the two
   things the docs don't state (section 1.2): whether the R0 trial checkout sends an ITN with the token straight
   away, and what `m_payment_id` recurring ITNs carry. The sandbox sends each ITN only once, so use the
   sandbox's ITN page to inspect them (https://developers.payfast.co.za/docs#sandbox).
   9b. **Live smoke test** (small real amounts, fees not refundable): a R5 donation, an admin refund of it,
   and an **Update card** round trip. These are the two features the sandbox can't exercise (section 1.6, section 1.7).
10. **Deploy config.** Add the `PAYFAST_*` / `PAYMENT_BACKEND` env vars wherever backend env is defined
    (Render env / `packages/infra` CDK secrets). Keep the passphrase in secrets, never in [`.env.shared`](../../../packages/backend/.env.shared).

---

## 6. Stripe regression guarantees

- With `PAYMENT_BACKEND=stripe`, every new branch is a no-op. `STRIPE_ENABLED` is computed the same way. (The
  default became `payfast` on 2026-10-01, so a Stripe deployment now sets the variable explicitly.)
- No Stripe file is deleted. The only existing lines that change are the tenant-deletion cancel block
  (moved as-is into `billing.cancel_tenant_subscription`) and additive lines in `signals.py`,
  [`config/schema.py`](../../../packages/backend/config/schema.py), [`config/urls_api.py`](../../../packages/backend/config/urls_api.py) and `settings.py`.
- The GraphQL schema only gains fields, so existing Stripe queries and generated types are unaffected.
- CI runs the existing backend and webapp-finances suites unchanged. PayFast tests use
  `override_settings(PAYMENT_BACKEND="payfast")`.

---

## 7. Environment variables

```bash
# Backend
PAYMENT_BACKEND=payfast           # or stripe
# ENVIRONMENT_NAME (existing) picks the credential set: "production" -> *_PRODUCTION on live
# PayFast, anything else -> *_DEVELOPMENT on the sandbox.
PAYFAST_MERCHANT_ID_DEVELOPMENT=10000100      # PayFast's public sandbox merchant
PAYFAST_MERCHANT_KEY_DEVELOPMENT=46f0cd694581a
PAYFAST_PASSPHRASE_DEVELOPMENT=<secret>       # your sandbox "Salt Passphrase"
PAYFAST_NOTIFY_URL_DEVELOPMENT=https://<tunnel>.ngrok-free.app/api/payfast/notify/
PAYFAST_MERCHANT_ID_PRODUCTION=<secret>
PAYFAST_MERCHANT_KEY_PRODUCTION=<secret>
PAYFAST_PASSPHRASE_PRODUCTION=<secret>        # required for subscriptions + API
PAYFAST_NOTIFY_URL_PRODUCTION=https://<api-host>/api/payfast/notify/
PAYFAST_VERIFY_SOURCE_IP=True     # False only for ngrok/local
# Prices (ZAR). Optional: the code defaults below apply when unset
PAYFAST_MONTHLY_PRICE=199.00
PAYFAST_YEARLY_PRICE=1990.00
PAYFAST_DONATION_AMOUNTS=50,100,150
# Existing, shared with Stripe: trial length for both backends
# SUBSCRIPTION_TRIAL_PERIOD_DAYS=7
# Frontend: nothing new (backend is read at runtime via paymentConfig)
```

Unlike the maintainer's other PayFast app, there are no RETURN_URL / CANCEL_URL variables: the backend
builds both from `WEB_APP_URL` plus the page the checkout started from, so every deployment gets the right
URLs automatically.

---

## 8. Risks

| Risk                                                                | Mitigation                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Wrong signature field order for subscription fields                 | Full documented order (section 1.3) + a test vector from the sandbox's signature tool                                                                                                                                                                                                                              |
| Missed or late ITN leaves the user "pending"                        | Return page polls; the daily reconcile task calls `/fetch`; ITN handling is idempotent                                                                                                                                                                                                                             |
| R0 trial checkout doesn't send an ITN immediately (docs are silent) | Sandbox check in step 9. We only learn the token from an ITN, so if no ITN arrives until the first real charge, the trial can't be activated from our side at checkout. We'd then stop and decide together (for example, record the trial locally from the return page and wait for the token on the first charge) |
| Failed renewals are silent (no failure ITN)                         | Daily `/fetch` of overdue renewals (section 2); PayFast also emails the buyer itself                                                                                                                                                                                                                               |
| Refunds and card update can't be tested in the sandbox              | Mocked unit tests + the live smoke test in step 9b                                                                                                                                                                                                                                                                 |
| Spoofed ITN                                                         | Signature + source IP + server `/validate` + expected amount from our own `PayFastCheckout`                                                                                                                                                                                                                        |
| Plan-change semantics differ from Stripe                            | Plan changes apply at period end, as Stripe does; `pendingPlan` is shown in the UI                                                                                                                                                                                                                                 |
| Switching an existing live deployment from Stripe to PayFast        | Existing Stripe subscribers aren't migrated automatically; `payfast_init_tenants` puts everyone on free. Document this as a one-way operational decision                                                                                                                                                           |

---

## 9. Decisions (agreed 2026-09-30)

1. **Prices:** set by env vars with code defaults: `PAYFAST_MONTHLY_PRICE` (R199.00),
   `PAYFAST_YEARLY_PRICE` (R1 990.00), `PAYFAST_DONATION_AMOUNTS` (R50/R100/R150). Prices are snapshotted
   per checkout and subscription (section 3.1).
2. **Parity with Stripe:** PayFast matches the Stripe implementation wherever both APIs allow it. That
   includes the 7-day trial (same `SUBSCRIPTION_TRIAL_PERIOD_DAYS`, once per tenant, card captured up front),
   trial-ending and payment-failed emails, transaction history labels, and the admin refund if the API allows.
   When PayFast can't match, section 2 lists the closest equivalent.
3. **Plan changes take effect at period end**, as the Stripe schedule's next phase does.
4. **Donations are in v1**: the same `/finances/payment-confirm` page and fixed-amount picker, paid through
   a PayFast once-off checkout.
5. **PayFast is the default backend** (agreed 2026-10-01): the maintainer serves South Africa, where Stripe
   isn't available. An unset `PAYMENT_BACKEND` means `payfast`. The web app still falls back to Stripe if the
   `paymentConfig` request fails, because the boilerplate's Stripe page tests rely on it. Stripe deployments set `PAYMENT_BACKEND=stripe`. Tests still pin `stripe` in
   `.test.env`, because the boilerplate's Stripe tests expect it.

The PayFast docs were read in full on 2026-09-30 (section 1). That resolved the three open items:

- **R0 trial checkout** is explicitly supported (https://developers.payfast.co.za/docs#subscriptions).
- **Signature order** follows the documented rule and each section's table order (section 1.3). It's pinned by a
  test vector from the sandbox's signature tool.
- **Refunds API** exists (https://developers.payfast.co.za/api#refunds) but can't be used in the sandbox,
  so it's tested live (step 9b).

The docs don't answer two things, which the sandbox run (step 9) will: whether a R0 checkout sends its
ITN straight away, and what `m_payment_id` recurring ITNs carry.

---

## 10. Implementation status (2026-09-30)

Built test-first (RED observed before every GREEN), on branch `feat/payfast-payment-backend`. Nothing committed.

**Backend** (`packages/backend`)

- [`apps/payfast/`](../../../packages/backend/apps/payfast/): [`constants.py`](../../../packages/backend/apps/payfast/constants.py), [`signature.py`](../../../packages/backend/apps/payfast/signature.py), [`client.py`](../../../packages/backend/apps/payfast/client.py), [`itn.py`](../../../packages/backend/apps/payfast/itn.py), [`models.py`](../../../packages/backend/apps/payfast/models.py) (+ [`migrations/0001_initial.py`](../../../packages/backend/apps/payfast/migrations/0001_initial.py)),
  [`services.py`](../../../packages/backend/apps/payfast/services.py), [`views.py`](../../../packages/backend/apps/payfast/views.py), [`urls.py`](../../../packages/backend/apps/payfast/urls.py), [`schema.py`](../../../packages/backend/apps/payfast/schema.py), [`tasks.py`](../../../packages/backend/apps/payfast/tasks.py), [`admin.py`](../../../packages/backend/apps/payfast/admin.py) (+ refund page template), [`checks.py`](../../../packages/backend/apps/payfast/checks.py),
  management commands `payfast_daily_maintenance`, `payfast_init_tenants`, `payfast_seed_demo`.
- [`apps/finances/billing.py`](../../../packages/backend/apps/finances/billing.py) (new dispatch); small additive edits to [`apps/finances/signals.py`](../../../packages/backend/apps/finances/signals.py),
  [`apps/multitenancy/schema.py`](../../../packages/backend/apps/multitenancy/schema.py) (tenant deletion calls `billing.cancel_tenant_subscription`), [`config/settings.py`](../../../packages/backend/config/settings.py),
  [`config/schema.py`](../../../packages/backend/config/schema.py), [`config/urls_api.py`](../../../packages/backend/config/urls_api.py), [`conftest.py`](../../../packages/backend/conftest.py), [`.env.shared`](../../../packages/backend/.env.shared).
- Tests: [`apps/payfast/tests/`](../../../packages/backend/apps/payfast/tests/) (unit: constants, signature, client, itn, checks, settings, models, services, tasks;
  integration: views, schema, admin; smoke: [`test_smoke.py`](../../../packages/backend/apps/payfast/tests/test_smoke.py)) and [`apps/finances/tests/test_billing.py`](../../../packages/backend/apps/finances/tests/test_billing.py),
  `test_payment_backend_settings.py`. Full backend suite: 874 passed.
- [`api.graphql`](../../../packages/webapp-libs/webapp-api-client/graphql/schema/api.graphql): PayFast types/fields added (129 lines), verified semantically identical to the live schema.

**Frontend** (`packages/webapp-libs/webapp-finances`, `packages/webapp`)

- [`src/payfast/`](../../../packages/webapp-libs/webapp-finances/src/payfast/): GraphQL documents, `usePaymentBackend`, `PaymentBackendSwitch`/`withPaymentBackend`,
  `submitPayfastCheckout`, pages (subscriptions layout, current plan, edit plan, cancel, payment method,
  transaction history, donation, return page) and their specs.
- [`src/routes/index.tsx`](../../../packages/webapp-libs/webapp-finances/src/routes/index.tsx): every exported route switches Stripe/PayFast; [`src/config/routes.ts`](../../../packages/webapp-libs/webapp-finances/src/config/routes.ts): `finances.payfastReturn`.
- [`packages/webapp/src/app/app.component.tsx`](../../../packages/webapp/src/app/app.component.tsx): Stripe `ActiveSubscriptionContext` only for Stripe; PayFast return route.

**Deviations from the plan above**

- Credentials are per environment (`*_DEVELOPMENT` / `*_PRODUCTION`, section 7), and `PAYFAST_SANDBOX` is derived from
  `ENVIRONMENT_NAME` instead of being an env var.
- Admin refunds only go to the payment source; bank-payout (EFT) refunds are sent to the PayFast dashboard.
- Daily maintenance also has a management command, so it can run from cron where there is no Celery beat.

**UI parity pass (2026-10-01).** The first PayFast pages diverged from their Stripe originals. They now
mirror them (same layout, wording and translation ids): the plan page shows Free, Monthly and Yearly with
the Stripe plan card ([`payfast/routes/subscriptionPlanItem.component.tsx`](../../../packages/webapp-libs/webapp-finances/src/payfast/routes/subscriptionPlanItem.component.tsx), a copy of
`routes/editSubscription/subscriptionPlanItem`), and the cancel page, transaction history tab and page,
payment method tab and donation form follow their Stripe versions. Differences kept only where PayFast
forces them: ZAR prices; the yearly saving is calculated from the env prices instead of hard-coded 17%;
the trial notice shows only while on Free (a PayFast trial starts with the first checkout); the payment
method tab links to PayFast's card update page instead of listing cards; the history's payment method
column says "PayFast" (ITNs don't include card details). As on Stripe, Free can't be selected on the plan
page; a paying organisation moves to Free by cancelling.

**Plan changes by checkout (2026-10-01).** PayFast's subscription update API
(`PATCH /subscriptions/:token/update`) fails in the sandbox: it returns an HTML "Whoops, looks like
something went wrong." page with HTTP 200 for every field, while `fetch` on the same subscription works
and a bad signature gets a proper JSON 401, so the request is authenticated and fails inside PayFast.
No public report of this was found; a maintained Laravel PayFast package
(https://github.com/fintech-systems/payfast-onsite-subscriptions) also changes plans without the update
API. So a paying organisation now switches plan with a new subscription checkout: R0.00 now, the new
price from the end of the current paid period (`billing_date`, https://developers.payfast.co.za/docs#subscriptions).
When its ITN arrives the new token is stored, the new plan becomes `pending_plan` (applied on the first
charge, at period end, as on Stripe) and the old subscription is cancelled; a failed cancel is kept in
`superseded_token` and retried by the daily task, so nobody is billed twice. The update-API code path
(`services.change_plan`, the `payfastChangePlan` mutation) was removed; `PayFastApiClient.update` remains
but is unused. Tests now pin `PAYMENT_BACKEND=stripe` in [`.test.env`](../../../packages/backend/.test.env), so a developer's `.env` choice can't
leak into the test run.

## 11. Human checks

Local setup, once (backend and web app via the README's `pnpm saas` commands):

1. In `packages/backend/.env` set `PAYMENT_BACKEND=payfast`, the four `PAYFAST_*_DEVELOPMENT` values
   (sandbox merchant `10000100` / `46f0cd694581a` and your sandbox passphrase), and `PAYFAST_VERIFY_SOURCE_IP=False`.
2. Expose the backend: `ngrok http 5001`, then set `PAYFAST_NOTIFY_URL_DEVELOPMENT=https://<id>.ngrok-free.app/api/payfast/notify/`.
3. `pnpm saas down` then `pnpm saas up`. Startup must show no `payfast.E00x` errors
   (remove one `PAYFAST_*_DEVELOPMENT` value to see the check name it, then put it back).
4. Sign up/log in at http://localhost:3000 as an organisation Owner, then seed history:
   `docker compose run --rm backend python manage.py payfast_seed_demo --email <your email>`.

Checks (each: what to do, what a correct result looks like):

1. Anyone can ask which backend is active:
   `curl -s -X POST http://localhost:5001/api/graphql/ -H 'Content-Type: application/json' -d '{"query":"{ paymentConfig { backend currency } payfastSubscriptionPlans { name amount interval } payfastDonationAmounts }"}'`
   → `backend: "payfast"`, `currency: "ZAR"`, plans 0.00 / 199.00 month / 1990.00 year, amounts 50.00 / 100.00 / 150.00.
2. The ITN endpoint rejects forgeries: `curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:5001/api/payfast/notify/ -d 'm_payment_id=x&payment_status=COMPLETE&signature=bad'` → `400`.
3. The ITN endpoint only accepts POST: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5001/api/payfast/notify/` → `405`.
4. Web app → Subscription → **Transaction history** shows the two seeded rows: "Donation" R 50.00 and "Monthly plan" R 199.00.
5. **Current subscription** shows "Free", with "Edit subscription" and no "Cancel subscription".
6. **Edit subscription** shows Monthly R 199.00 / month and Yearly R 1 990.00 / year, each saying it "Starts with a free trial".
7. Choose **Monthly** → you land on sandbox.payfast.co.za showing R 0.00 today and R 199.00 recurring. Pay with the sandbox wallet.
8. You come back to "Confirming your payment…", then the subscription page with a "Payment successful" toast:
   plan **Monthly**, a **Free trial expiry date** 7 days away. (In the sandbox dashboard → ITN, the notification shows as delivered.)
9. **Edit subscription** again: Monthly says "Current plan"; choose **Yearly** → PayFast sandbox shows R 0.00 now and
   R 1 990.00 yearly from the end of your current period → confirm → back via the return page, the subscription page shows
   **Next billing plan: Yearly**, and the plan page marks Yearly "Scheduled". In the PayFast sandbox dashboard the old
   monthly subscription is cancelled and the new yearly one is active.
10. **Payment methods** says the card is stored by PayFast and has **Update card** (the page itself only works on live PayFast, section 1.6).
11. **Cancel subscription** → Continue → toast about moving to the free plan at the end of the period; the page now shows
    **Expiry date** instead of Next renewal, and no Cancel button.
12. Sidebar → **Payments** (donation page): choose R 100.00 → **Pay** → PayFast sandbox → pay → back via the return page to
    Home with "Payment successful"; Transaction history lists a new "Donation" R 100.00.
13. Django admin (http://localhost:5001/admin/, superuser) → PayFast → PayFast payments → open the donation → "Refund this
    payment via PayFast" opens the refund form (actual refunds only work on live PayFast, section 1.7).
14. Switch back: `PAYMENT_BACKEND=stripe`, restart → the subscription pages are the original Stripe ones,
    and check 2's endpoint returns `404`.

## 12. Known issues to fix (found 2026-10-01)

Found in the code review behind the walkthrough
([`2026-10-01-payfast-walkthrough.md`](../specs/2026-10-01-payfast-walkthrough.md)). Not fixed yet. In order
of risk; each is fixed test-first (RED before GREEN), and the walkthrough is updated in the same change.

1. **A missed renewal ITN loses data.** When a renewal's ITN never arrives, the daily task's
   `_check_overdue_renewal` in [`services.py`](../../../packages/backend/apps/payfast/services.py) catches up
   the period dates from `GET /fetch` but records no `PayFastPayment`, so the charge is missing from the
   transaction history. If that renewal is the first charge after a plan switch, it also doesn't apply
   `pending_plan`, so the organisation stays on the old plan for a period. Fix: the catch-up should apply a
   pending plan and record the charge (marked as caught up), as `_renew` does.
2. **A charge on a replaced subscription isn't recorded.** While `superseded_token` is still waiting to be
   cancelled (see `_cancel_superseded`), PayFast can still bill the old subscription. That ITN's token matches
   no subscription, so `process_itn` ignores it: the money is taken but not recorded. Fix: match ITNs on
   `superseded_token` too, record the payment, and flag it (log an error) so it can be refunded.
3. **Repeated "payment failed" emails.** In `_check_overdue_renewal`, a failed first charge after a trial
   sends `SubscriptionErrorEmail` and then cancels the subscription. If that cancel call fails, the "sent"
   timestamp is never saved, so the next daily run sends the email again. Fix: save
   `payment_failed_notified_at` before the cancel attempt.
4. **Cancellation ITNs are rejected.** Seen in the sandbox on 2026-10-01: the `CANCELLED` ITN PayFast
   sent for a replaced subscription got HTTP 400, logged as "PayFast did not confirm the notification"
   (PayFast's `/eng/query/validate` didn't answer `VALID`). Harmless there, since that token had been
   replaced, but it means a cancellation made on PayFast's side (the buyer's email link, or the merchant
   dashboard) would never reach the app, and PayFast keeps retrying. Fix: find out what `/eng/query/validate`
   expects for cancellation ITNs (they carry no amount), and handle them without weakening the other checks.
5. **The current-plan page can show a price that will never be charged.** After switching during a trial
   (seen 2026-10-01), the page shows "Monthly R199.00 / month" (the replaced subscription's agreed price)
   and "Next billing plan: Yearly", while what PayFast will actually charge is R10.00 a year from 8 October.
   Fix: show what's charged next and when, e.g. "Free trial until 8 October, then Yearly R10.00 / year".
6. **Minor:**
   - The billing read queries in [`schema.py`](../../../packages/backend/apps/payfast/schema.py)
     (`payfastActiveSubscription` and friends) don't call `require_payfast()`, and `get_subscription` creates
     an empty `PayFastSubscription` row on read, even on a Stripe deployment. Fix: refuse on Stripe, as the
     mutations do.
   - [`payfast_seed_demo`](../../../packages/backend/apps/payfast/management/commands/payfast_seed_demo.py) says
     "development only" but would also run in production. Fix: refuse when `PAYFAST_ENVIRONMENT` is
     `production`.
   - The return page's "Go to my subscription" link after a timeout
     ([`payfastReturn.component.tsx`](../../../packages/webapp-libs/webapp-finances/src/payfast/routes/payfastReturn.component.tsx))
     is also shown after a donation, where Home would fit better.
   - Section 2's behaviour table and section 4's file list in this plan still describe the removed update-API plan change
     (`PATCH /update`, `changePlan`); section 10 records what replaced it. Fix: update those passages.
