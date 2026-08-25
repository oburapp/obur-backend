# Threat Model

> **Status: point-in-time assessment, 2026-08-25.** This maps
> `obur-backend`'s current implementation against the
> [OWASP API Security Top 10 (2023)](https://owasp.org/API-Security/editions/2023/en/0x11-t10/),
> the standard framework for this kind of system (a pure REST API, no
> server-rendered HTML), plus a few general concerns it doesn't cover.
> Every "current state" line below was checked against the real source
> files listed, not assumed from memory or from what the code is
> supposed to do. Re-check this when a phase that changes the attack
> surface lands (Phase 10 blocking/reporting, Phase 15 media uploads,
> `obur-web`/`obur-mobile` going live), not just on a fixed schedule.

## Summary matrix

| # | Category | Relevance | Current risk | Action needed now |
|---|----------|-----------|---------------|---------------------|
| API1 | Broken Object Level Authorization | Very High | **Low** | None |
| API2 | Broken Authentication | High | **Low-Medium** | Set `authorized_parties` once `obur-web`/`obur-mobile` exist |
| API3 | Broken Object Property Level Authorization | High | **Low** | None |
| API4 | Unrestricted Resource Consumption | High | **Low** (today) | None yet; enforce the planned upload cap when Phase 15 ships |
| API5 | Broken Function Level Authorization | Medium | **Low** | None yet; keep `require_admin` discipline as Phase 10 grows the admin surface |
| API6 | Unrestricted Access to Sensitive Business Flows | Medium | **Low-Medium** | None; fraud/fake-account tooling is a documented, deliberate PDD §17 deferral |
| API7 | Server Side Request Forgery | None | **None** | None; revisit when R2 or a Geocoding proxy adds outbound calls |
| API8 | Security Misconfiguration | High | **Low** | Make an explicit call on public `/docs` in production (see below) |
| API9 | Improper Inventory Management | Medium | **Low** | None |
| API10 | Unsafe Consumption of APIs | Medium | **Low** | Apply the same signature-verify + schema-validate pattern to future integrations |

Everything below "Beyond the API Top 10" isn't in the OWASP list but is a
standard question worth a straight answer.

---

## API1:2023 - Broken Object Level Authorization

Returning or modifying an object by ID without checking the caller can
actually access *that specific* object. The classic IDOR case, and the
single most common real-world API vulnerability class.

**Relevance:** Very high. Nearly every endpoint is object-ID-keyed
(checkins, lists, venue saves, notifications, users).

**Current state:** Two independent layers, not one:

- **Application layer** - `app.core.authz.can_view` /
  `ensure_visible_and_owned` gate every read and mutation.
  Existence-leak protection is built in: a resource a caller can't see
  returns the same 404 a nonexistent id would, never a 403 that would
  confirm the id belongs to something real.
- **Database layer** - Row Level Security on all 15 application tables
  (ADR-0016, Phase 8), the layer that survives a query forgetting to
  call the application check. Verified with fail-closed and
  application/RLS-parity integration tests
  (`tests/integration/test_rls_policies_integration.py`).

**Risk: Low.** The best-covered category in the codebase, and the one
this whole Phase 8 effort was built around.

**Action:** None now. `CLAUDE.md`'s Security section now states RLS is
mandatory for every new table, no silent exceptions, so this stays true
going forward rather than eroding one new feature at a time.

---

## API2:2023 - Broken Authentication

Weak or missing session/token validation, enabling credential stuffing,
token forgery, or replay.

**Relevance:** High. Every authenticated endpoint depends on it.

**Current state:** Token verification is delegated entirely to Clerk's
own SDK (`clerk_backend_api.security.authenticate_request_async` in
`app/core/security.py`), not hand-rolled JWT parsing - the highest-risk
mistakes in this category (accepting `alg: none`, weak signature
checks) aren't something this codebase can get wrong, because it never
touches the token's cryptography directly. Suspended and frozen account
states are handled explicitly (`app/core/auth.py`).

One known, already-tracked gap: `authorized_parties` (the `azp` claim)
is intentionally left unset, and
[app/core/security.py:27-29](app/core/security.py) says so directly.
Current impact is low: there is exactly one Clerk application, so there
is nothing else a token could be confused with yet. It stops being low
impact the moment a second origin exists.

**Risk: Low-Medium.** Mostly low, carried down by the one explicit open
item.

**Action:** Set `authorized_parties` to `obur-web` / `obur-mobile`'s
real origins once they exist - already tracked in
`docs/deployment.md`'s "Still open" section, not a new finding here.

---

## API3:2023 - Broken Object Property Level Authorization

Combines the older "Excessive Data Exposure" (API returns more fields
than it should) and "Mass Assignment" (API accepts and applies fields
it shouldn't) into one category: does the API control *which object
properties* flow in and out, not just whether the caller is authorized
at all.

**Relevance:** High. Every endpoint reads and writes model data.

**Current state:** Every endpoint has an explicit Pydantic request and
response schema (`CLAUDE.md` API Design rules); ORM objects are never
serialized directly. A request schema for, say, `PATCH /users/me`
simply has no `role` field to assign, so there is nothing to send that
would escalate privilege, structurally, not by a runtime check that
could be missed.

**Risk: Low.**

**Action:** None. Already an enforced, existing standard, not something
this assessment is introducing.

---

## API4:2023 - Unrestricted Resource Consumption

No caps on request rate, payload size, or expensive operations, letting
one caller exhaust shared resources.

**Relevance:** High.

**Current state:**

- Rate limiting is live on every endpoint (ADR-0014): a generous
  baseline tier, a strict tier on abuse-sensitive writes, Redis-backed,
  keyed on user id once known.
- Pagination is mandatory on every list endpoint. The one deliberate
  exception (the category catalog, served whole because it's a tree)
  has its own bound (`MAX_CATALOG_SIZE`) enforced by a test, so the
  exception stays a decision rather than an oversight.
- A file-upload size cap (~15MB) is *planned*, not yet built - there is
  no upload endpoint at all yet (Phase 15, Media Pipeline). Checked via
  `grep` for `httpx`/`boto3`/`AsyncClient` usage in `app/`: none exists
  outside tests, confirming there's genuinely nothing to cap yet.

**Risk: Low today.** Becomes a real, unmitigated risk the moment Phase
15 ships an upload endpoint without the cap actually implemented, not
just documented as intent.

**Action:** None now. When Phase 15 starts, treat the ~15MB cap as a
requirement to test, not a line in a doc to trust.

---

## API5:2023 - Broken Function Level Authorization

A caller invoking a function/endpoint their role shouldn't permit at
all (distinct from API1: this is "can you call this endpoint," not
"can you touch this specific object").

**Relevance:** Medium today, will grow with Phase 10's moderation
surface.

**Current state:** `app.core.authz.require_admin` is a single, reusable
FastAPI dependency (`Depends(require_admin)`), currently the gate on
the one existing admin endpoint
(`DELETE /admin/checkins/{id}` in `app/api/v1/admin.py`). Clean,
centralized pattern; there is no second, inconsistent way an endpoint
checks for admin today.

**Risk: Low.** Small surface, correctly gated.

**Action:** None now. When Phase 10 adds the report queue,
`USER.status` moderation, and venue verification booleans to
`admin.py`, every new route must use `require_admin`, not a bespoke
inline `if current_user.role != "admin"` - worth a deliberate check at
that phase's start, the same way RLS now has one.

---

## API6:2023 - Unrestricted Access to Sensitive Business Flows

A legitimate, correctly-authenticated flow (account creation, follow,
check-in creation) gets abused at volume - bot mass-following, spam
check-ins - which plain rate limiting doesn't fully solve, since each
individual request is valid.

**Relevance:** Medium. Check-in creation, venue creation, and follow
are exactly this shape of flow.

**Current state:** These specific endpoints already sit on the strict
rate-limit tier (ADR-0014, Phase 7's own scoping: "check-in creation,
report submission, venue creation, and follow"), which is a real,
if partial, mitigation for this category even though it wasn't
originally framed in these terms. Fraud and fake-account tooling
(phone verification, device fingerprinting) is *not* built - but PDD
§17 defers this deliberately until real abuse is observed, a stated
decision in `docs/roadmap.md`'s Out of Scope section, not a gap nobody
noticed.

**Risk: Low-Medium.** Rate limiting narrows this without closing it;
the remaining exposure is an accepted, documented tradeoff.

**Action:** None now. Revisit only if real abuse is actually observed
post-launch, per the existing PDD decision - building fraud tooling
pre-emptively against a hypothetical is explicitly what PDD §17 argues
against.

---

## API7:2023 - Server Side Request Forgery (SSRF)

Tricking the server into making a request to an internal or arbitrary
external destination based on caller-controlled input (e.g., a URL
field the server fetches on the caller's behalf).

**Relevance:** Currently none. Verified directly: no `httpx`, `boto3`
client instantiation, or any outbound HTTP call exists anywhere in
`app/` outside test mocks. Venue geocoding is deliberately
client-resolved - per ADR-0009, "the backend never calls Google, it
stores what the client already resolved" - which happens to eliminate
this vulnerability class for that feature entirely, not just mitigate
it.

**Risk: None currently.**

**Action:** None now. Revisit the moment R2 (Phase 15) or any future
backend-proxied Geocoding endpoint (explicitly out of scope today, see
`docs/roadmap.md`) is built - any endpoint that fetches a URL derived
from user input needs an allowlist at that point, not after.

---

## API8:2023 - Security Misconfiguration

Overly permissive CORS, leaked stack traces, unnecessary exposed
surface, insecure defaults left untouched.

**Relevance:** High, the broadest category.

**Current state:**

- CORS (`app/main.py`) uses an explicit origin allowlist from
  `CORS_ORIGINS`, never a wildcard, even though `allow_credentials=True`
  is set - the one combination where a wildcard origin would be a real
  hole.
- RFC 9457 problem responses (ADR-0015) already closed roughly fifteen
  endpoints that used to leak raw exception text to clients; stack
  traces don't reach responses.
- **One undecided default, found while writing this document, not
  previously flagged:** FastAPI's interactive docs (`/docs`, `/redoc`,
  `/openapi.json`) are exposed with the framework's default settings, in
  every environment including production - nobody has actively decided
  this either way, it's just what happens when `docs_url` is never set.

**Risk: Low**, carried by that one open default. Publicly documented
APIs are a completely normal, deliberate choice (Stripe, GitHub both do
it) - the point isn't that it's wrong, it's that right now it's an
accident of omission rather than a decision.

**Action:** Decide explicitly: keep `/docs` public (fine, if intended,
`obur-web`/`obur-mobile` developers may want it), or gate it (e.g.
`docs_url=None` unless `settings.environment != "production"`). Either
answer is acceptable; leaving it undecided is the actual issue.

---

## API9:2023 - Improper Inventory Management

Undocumented or forgotten ("shadow") API versions, stale environments,
unclear ownership of what's actually deployed and where.

**Relevance:** Medium.

**Current state:** Single API version (`/api/v1`), no deprecated or
parallel versions yet. The full endpoint surface is enumerable from the
auto-generated OpenAPI spec. What's actually deployed, where, and how
is now written down for real (`docs/deployment.md`), verified against
the live Railway service rather than assumed.

**Risk: Low.** Small, single-version, and, as of this Phase 8 work,
actually documented rather than tribal knowledge.

**Action:** None now. Worth a second look the first time a `/api/v2` or
a deliberately-deprecated endpoint exists; no such plan exists today.

---

## API10:2023 - Unsafe Consumption of APIs

Trusting a third party's response or webhook without verifying its
authenticity or validating its shape.

**Relevance:** Medium. The Clerk webhook is the one real case today.

**Current state:** The Clerk webhook (`app/api/v1/webhooks.py`)
verifies an HMAC signature via the official `svix` library before
touching the payload, fails closed if `CLERK_WEBHOOK_SECRET` is
unconfigured (raises rather than skipping verification), and validates
the payload against a Pydantic schema (`ClerkWebhookEvent`) before any
of it is used. This is the correct shape for consuming an external
system: verify authenticity, then validate structure, in that order.

**Risk: Low.**

**Action:** None now. Apply the identical pattern (signature or
equivalent authenticity check, then schema validation) to R2 (Phase 15)
and any other third-party integration added later.

---

## Beyond the API Top 10

Not part of the OWASP API list, but standard questions worth a direct
answer rather than leaving them implicit.

**Transport security (HTTPS/TLS).** Production traffic is HTTPS only:
Railway's provisioned domain carries TLS automatically, verified
directly (`curl https://obur-backend-production.up.railway.app/health`).
Local development is plain HTTP, which is standard and not a risk:
that traffic never leaves the machine.

**CSRF (Cross-Site Request Forgery).** Not in the API Top 10 because
it's fundamentally a cookie-session problem, and this API doesn't use
one - auth is a Bearer token in the `Authorization` header, which a
browser never attaches to a cross-site request automatically the way it
does a cookie. This class of attack doesn't apply to the current auth
model.

**Dependency / supply-chain vulnerabilities** (OWASP's general Top 10,
A06:2021, "Vulnerable and Outdated Components"). `uv.lock` pins exact
versions, which gives reproducibility but doesn't by itself say whether
a pinned version has a disclosed CVE. Closed by two layers, added in
the same pass as this document: an `audit` job in
`.github/workflows/ci.yml` runs `uv audit` (checks every pinned
dependency against the OSV database) on every PR, and
`.github/dependabot.yml` covers both the `uv` and `github-actions`
ecosystems for ongoing, scheduled update PRs. Dependabot's *alerts*
feature (the part that actually watches for newly-disclosed CVEs
between scans, not just the config file) still needs enabling once,
by hand, in GitHub repo Settings -> Security -> Code security, a
committed file can't turn that on by itself.

**Secrets management.** Credentials are read from the environment only,
never hardcoded (`CLAUDE.md`'s own Forbidden list); `.env` is
gitignored and was confirmed never committed. Railway's own variables
are the production equivalent, no separate secrets manager is in use
(reasonable at the current scale).
