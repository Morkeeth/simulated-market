# First Users

First Users starts with a public app address and one read-only task. Software visitors attempt it first; the same task can be downloaded as a project brief for verified humans through FAVOUR. The exported brief is not an integration, posting, funding or booking.

## Local front door

Install requirements-app-check.txt and Playwright Chromium as described in the README. Then run:

```sh
python -m sim.first_users --store ../first-users-private --port 3899
```

Open http://127.0.0.1:3899/. Paste an authorized running app address without credentials or query parameters. Confirm the task, acknowledge practice checkout, run a basic browser check, inspect saved screens, create a report link, and download the FAVOUR draft. Practice checkout makes no charge and supplies no real entitlement. A basic check can inspect page/link loading; it cannot establish that the chosen task was completed.

Real model visits require explicit operator enablement with --allow-models, a Token Factory key and an isolated bounded cost account. Set SIM_PROVIDER_ROOT, SIM_PROVIDER_CAP_USD and SIM_PROVIDER_STOP_USD to the approved values before starting. Model visits are read-only. The models can misinterpret tasks; check their evidence before reporting completion. The content guard rejects navigation-only pricing claims but is a bounded English heuristic and can reject valid quotes.

Stripe test checkout is enabled only by STRIPE_TEST_SECRET_KEY or a sk_test_ secret in ~/.config/keys/stripe-test.key. A live secret is refused. The return URL cannot grant a check: the server retrieves the test Checkout Session and verifies paid status, EUR1900cents and matching job metadata. No test key was available during the recorded local validation; this adapter has no Stripe runtime proof. Use Stripe-hosted confirmation for the first manual Payment Link order until the real application origin exists; never insert a fabricated hosted URL.

## Hosted sample mode

Append --sample to bind a keyless sample server. The app accepts bundled working/broken samples only; it does not visit caller URLs or run models. The pay step is practice-only even if a server key exists. It allows ten checks per anonymous tenant/day and twenty total checks per store. One worker has a45-second basic deadline. The SQLite quota is transactional; a new store resets it, so it is not a global spending cap. The sample is not an authenticated multi-tenant product.

Report links are seven-day bearer capabilities. Anyone holding the link can see that report and its screens; a new link revokes the previous one. Screens may contain sensitive target content: review before sharing. The links are local until the app is actually hosted. The public sample is not a route into private workspaces or customer URLs.

## Queue and human handoff

SQLite/WAL stores tenant ownership, immutable request identity, daily quota and micro-USD per-run cap. Fenced leases reject stale/duplicate settlement. Front-door jobs do not silently retry after a lease expires. A crashed external provider call remains a reconciliation problem, not an exactly-once inference guarantee. The local queue is single-node; distributed workers and durable object storage remain future work.

The handoff uses URL, three proposed question IDs, a reward plan and a five-card review deck. The proposed ten reviews at0.5USDC each remain unfunded. Question IDs belong to this draft format; current FAVOUR API compatibility is unverified. A human must post and sign the builder's funding. Human identity, tester supply, mobile handoff and calibrated simulation remain unverified.

## First paid offer

The first offer is First Users at EUR19 for one software check and a manually reviewed report. It includes no human-test reward budget. No payment or demand is established by the local prototype. A paid service needs an activated merchant account, real fulfillment/privacy/retention operations and outside-user acceptance; do not treat sample mode as those gates.
