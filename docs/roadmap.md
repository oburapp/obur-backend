# Backend Roadmap

Phased build order for `obur-backend`. Milestone-level, not task-level —
granular work items belong in GitHub Issues, not here. Phases are ordered
by dependency: each one unblocks the next, so building out of order creates
rework. See [pdd/obur-pdd.md](https://github.com/oburapp/obur-docs/blob/main/pdd/obur-pdd.md)
for the product rationale behind each domain.

This roadmap covers `obur-backend` only. A real end-to-end login — a user
actually completing a Clerk sign-in flow — also needs `obur-web` and/or
`obur-mobile` to integrate the Clerk client SDK. That's tracked in those
repos, not gated by this phase order.

**This roadmap is scoped to cover the PDD in full.** The goal is that once
`obur-web` / `obur-mobile` development starts, no one has to come back to the
backend for a missing capability. Two sections make that claim auditable
rather than asserted: [Out of Scope](#out-of-scope) lists what the PDD
mentions that this roadmap deliberately does *not* build, with reasons, and
the [PDD Coverage Matrix](#pdd-coverage-matrix) maps every feature-catalog
row, every table, and every non-functional requirement to a phase or to an
out-of-scope line.

A release is cut when there is something worth releasing, not once per phase.
Phases are units of work; versions are units of delivery, and tying the two
together only forces releases nobody needs. The release flow itself is the
shared one in [obur-docs/CLAUDE.md](https://github.com/oburapp/obur-docs/blob/main/CLAUDE.md#versioning-and-releases).
`1.0.0` is the exception, and it is pinned to Phase 18 for a reason stated there.

---

## Standing Rules

Phases 0–4 were built before most cross-cutting concerns existed, and the
original roadmap deferred all of them to a single late phase. That is the
structural reason this document needed rewriting: a concern deferred to the
end has to be retrofitted across everything already built. From Phase 7
onward the mechanisms exist up front, and *applying* them is part of every
phase's definition of done — not a later phase's problem.

Every phase from Phase 7 onward is complete only when all of the following
hold for the work it adds:

1. **RLS policy authored for every new table** — or a written justification
   for why that access pattern needs a bypass (platform-wide counts, admin
   moderation tooling). Deciding this while the query is being written is far
   cheaper than re-auditing later (PDD §17). Applies from **Phase 8**, which
   is where the mechanism lands; there is nothing to author against before
   the role split exists.
2. **Every new endpoint declares a rate-limit tier** — baseline, or the
   strict tier for actions where repeated abuse does real damage (PDD §17).
3. **Every list endpoint is paginated and capped** via
   `app/core/pagination.py`. No unbounded response, and no bulk-export
   endpoint — a standing design principle, not merely an absent feature.
4. **Every new read path applies the block, mute, and `USER.status`
   filters** that apply to it. These are query inputs, not a layer added
   after the fact.
5. **An N+1 query-count test** for every list endpoint that attaches nested
   data, using the existing `query_counter` fixture — see
   [testing-strategy.md](testing-strategy.md).
6. **Coverage stays at or above 98%.**
7. **A `CHANGELOG.md` entry lands in the same PR** as the change itself.
8. **If a decision changed, the PDD / ER diagram / ADR are updated in the
   same PR.** This is the rule that prevents a repeat of the drift this
   document was rewritten to correct — documentation that lags behind
   shipped code is what produced it.
9. **The repo's own code standards hold** — 300-line file limit, no magic
   values, `X | None` syntax, service-layer queries only. See
   [CLAUDE.md](../CLAUDE.md).

---

## Phase 0 — Bootstrap

- `uv init`, `pyproject.toml`, core dependencies (fastapi, uvicorn, sqlalchemy[asyncio], alembic, asyncpg, pydantic-settings, redis, boto3)
- `app/` skeleton per [project-structure.md](project-structure.md)
- `docker-compose.yml`: PostgreSQL + PostGIS, Redis
- `app/core/config.py` (pydantic-settings reading `.env.example` keys)
- `app/main.py`: FastAPI app, lifespan, `/health` checking real DB + Redis connectivity
- Alembic initialized, first (empty) migration applies cleanly

**Why first:** nothing else runs without a working app + DB connection + migration pipeline.

## Phase 1 — Identity & Auth

- `USER` model (with `auth_provider` / `auth_provider_id`, not a
  Clerk-specific field name — see rationale below) + first real migration
- Clerk JWT verification middleware (`app/core/security.py`), isolated so
  no other module imports Clerk directly — everywhere else sees our own
  `User`, not a Clerk type
- Auth dependency for protected routes; public routes explicitly marked
- Clerk webhook endpoint (`user.created` / `user.updated` / `user.deleted`)
  with signature verification, as the primary sync mechanism — a profile
  change made via Clerk's own UI (e.g. email) must reach every client, not
  just the one that made it
- JIT provisioning in the auth dependency as a fallback only, for the race
  where a first request arrives before the webhook does
- `GET /api/v1/users/me`

**Why webhook + JIT, not JIT alone:** JIT alone only fires on first-seen
login — it never revisits a user afterward, so a Clerk-side change (e.g.
email updated through Clerk's own account UI) would never reach our
`USER` row. Auth and cross-device consistency are foundational enough
that this needed the correct mechanism, not the cheaper one — this phase
grew beyond its original one-line sketch for that reason.

**Why now:** every other domain has a `user_id` FK and needs a verified identity to attach writes to.

**Deferred from this phase, on purpose:**
- The Clerk webhook is built and unit-tested but not yet registered with
  Clerk — that needs a public URL, which doesn't exist until deployment.
  Until then it fails closed (clean 401), not silently. Picked back up in
  Phase 8.
- `authorized_parties` (the `azp` claim check) is left unset in
  `app/core/security.py`. Safe for now: there's a single Clerk application
  and no second app to confuse a token with, so the check has nothing to
  guard against yet. Set it once real `obur-web`/`obur-mobile` origins
  exist — Phase 8.

## Phase 2 — Venues & Products

- `VENUE_CATEGORY` (+ translation), `GLOBAL_PRODUCT_TYPE` (+ translation), `VENUE`, `PRODUCT`, `VENUE_SAVE` models. **Superseded in Phase 5**: `GLOBAL_PRODUCT_TYPE` (+ translation) and `PRODUCT` are dropped with the rest of the product layer (ADR-0011) — kept here for the historical record of what Phase 2 actually shipped.
- Venue creation with 50m-radius duplicate detection (PostGIS)
- Venue search: `pg_trgm` word-similarity matching on name, diacritics
  folded via `unaccent` — language-agnostic and typo-tolerant, chosen
  over PostgreSQL FTS's language-locked config once the requirement was
  clarified as "any language, partial input, typos" (see ADR-0003 in
  obur-docs)
- `GET/POST /api/v1/venues`, `GET/POST /api/v1/products`

**Why now:** check-ins reference a venue and its products — this domain has to exist before check-ins can.

## Phase 3 — Check-in Core Loop

- `CHECKIN`, `CHECKIN_PRODUCT` models. A product can't be rated twice in
  the same check-in (unique constraint); `rating`/`rating_service`/
  `rating_ambiance`/`rating_value` are all constrained to the PDD §8
  four-point scale at the DB level, not just in application code.
  **Superseded in Phase 5**: `CHECKIN_PRODUCT` is dropped and the venue
  criteria become four, all required (ADR-0011). The four-point scale and
  its DB-level constraint are unchanged — kept here for the historical
  record of what Phase 3 actually shipped.
- Create-checkin service: one `CHECKIN` + N `CHECKIN_PRODUCT` rows in a
  single transaction. Rejects an empty product list, a duplicate product
  in the same submission, a product no longer available at the venue,
  and a `visited_at` in the future relative to the visitor's own
  timezone (`visited_tz`) — not the server's, since a visitor east of
  UTC logging a visit in their early morning hours must not be rejected
  just because the server's UTC date hasn't rolled over yet.
- `is_public` is the only visibility control (no separate "contribute to
  statistics" toggle — see the PDD's share step, and obur-docs for why that
  toggle was dropped): it gates both feed visibility and aggregate
  rating inclusion. **Superseded in Phase 4**: replaced by a shared
  three-tier `visibility` field (see Phase 4 below and ADR-0006 in
  obur-docs) — kept here for the historical record of what Phase 3
  actually shipped.
- `POST/PATCH/DELETE /api/v1/checkins/{id}`, `GET /api/v1/checkins/{id}`,
  `GET /api/v1/venues/{id}/checkins`, `GET /api/v1/users/{id}/checkins`.
  A private check-in is invisible to anyone but its owner or an admin —
  indistinguishable from a nonexistent one (404, not 403), so its
  existence is never leaked.
- Deleting a check-in is a soft delete (`deleted_at`), never a real
  `DELETE` — a check-in that already contributed to an awarded badge or
  an aggregate rating must not retroactively corrupt that history. A
  separate admin-only endpoint (`DELETE /api/v1/admin/checkins/{id}`)
  can permanently purge one, for moderation/takedown cases — deliberately
  not a query flag on the regular delete endpoint, so a destructive,
  irreversible action can't be triggered by accident.
- `USER.role` (`user` | `admin`, a plain extensible string, not a
  boolean): the first place authorization is more than "is this your own
  resource" — an admin may act on anyone's. Never settable through any
  user-facing endpoint or the Clerk webhook; the first admin account is
  set directly in the database, once, by hand.
- Ownership authorization (`app/core/authz.py`): a user may act on their
  own check-in; an admin may act on anyone's. This is the first place
  "is this `current_user` allowed to do this" matters — built here,
  alongside the endpoints that need it, not as a separate upfront auth
  phase — and written generically enough to be reused as-is once other
  user-owned resources (Phase 4's lists, likes) exist.

**Why now:** this is the product's core action (PDD §10) and the dependency root for aggregate scoring, badges, and feed — build and stabilize it before anything downstream consumes it.

## Phase 4 — Social Graph & Engagement

- `FOLLOW`: one-directional, no approval required (self-follow rejected
  at both the service layer and a DB `CHECK` constraint). Either party
  can end it — the follower unfollowing, or the followed user removing
  that follower from their own followers list.
- Shared three-tier `visibility` (`public` / `close_friends` / `private`)
  replacing `CHECKIN`'s old `is_public` boolean, extended identically to
  `LIST` and `VENUE_SAVE` — one authorization function
  (`app.core.authz.can_view`) enforces all three alike. `VENUE_SAVE`
  defaults to `private` (unlike `CHECKIN`/`LIST`'s `public` default) —
  saving a venue is a personal tracking action first. See ADR-0006 in
  obur-docs.
- `CLOSE_FRIEND`: a manually curated subset of a user's own followers,
  not a "followers-only" tier — the open, no-approval follow model gives
  "followers-only" no real access-control meaning. The composite foreign
  key to `FOLLOW` (`ON DELETE CASCADE`) does two jobs at the database
  level: a close friend must currently be a follower, and unfollowing
  automatically revokes close-friend status. Modeled on Letterboxd's own
  close-friends feature — verified against a real comparable product,
  not designed from first principles.
- `LIST`, `LIST_ITEM`: real (hard) delete, unlike `CHECKIN`'s soft
  delete — no badge or aggregate depends on list contents. Item ordering
  uses fractional indexing (`ListItem.position`, the
  `fractional-indexing` package), so inserting, moving, or removing an
  item writes only that one row, never renumbering neighbors. Requires
  `COLLATE "C"` on the column — found and fixed via an empirical
  before/after test against the real database after the default
  locale-aware collation was found to silently break the algorithm's
  byte-ordering assumption. See ADR-0007 in obur-docs.
- `CHECKIN_LIKE`, `LIST_LIKE`: a visible social signal, separate tables
  per target type (not a shared polymorphic table) for real foreign-key
  integrity. Liking something requires being able to see it first — a
  private check-in can't be liked by anyone but its owner.
- `CHECKIN_BOOKMARK`, `LIST_BOOKMARK`: a private save-for-later note,
  always separate from likes — no bookmark count is ever exposed to
  anyone but the bookmarker. Listing bookmarks re-checks the target's
  current visibility, not just its visibility at bookmark time — content
  made private after being bookmarked silently drops out of the
  bookmarker's own list too. See ADR-0006 in obur-docs.
- `NOTIFICATION`: created synchronously, in the same transaction as the
  action that triggers it — no queue, no background worker.
  `read_at` lives on the backend row (not per-device client state), so
  read status is automatically consistent across every device a user is
  signed into. `target_type`/`target_id` deliberately isn't a real
  foreign key, unlike the like/bookmark tables — a notification is a
  transient record, not data whose own correctness depends on the
  target still existing. See ADR-0008 in obur-docs.
- Existence-leak fix applied uniformly across `CHECKIN`, `LIST`, and
  `VENUE_SAVE` mutation endpoints (`app.core.authz.ensure_visible_and_owned`):
  a non-owner acting on a resource they can't even see gets the same 404
  a nonexistent id would, never a 403 that would confirm the id belongs
  to something real — found via adversarial testing (a stranger `PATCH`ing
  a private check-in got 403, leaking its existence, before the fix) and
  applied to every owner-gated mutation across all three resource types,
  not just the one it was first found on.
- Endpoints: `POST/DELETE /users/{id}/follow`, `GET /users/{id}/followers`,
  `GET /users/{id}/following`, `DELETE /users/me/followers/{id}`,
  `POST/DELETE /users/me/close-friends/{id}`, `GET /users/me/close-friends`,
  full `LIST` CRUD plus item add/move/remove
  (`POST/GET/PATCH/DELETE /lists/...`), `POST/DELETE /checkins/{id}/like`,
  `POST/DELETE /lists/{id}/like`, `POST/DELETE /checkins/{id}/bookmark`,
  `POST/DELETE /lists/{id}/bookmark`, `GET /users/me/bookmarks/checkins`,
  `GET /users/me/bookmarks/lists`, full `VENUE_SAVE` CRUD
  (`POST/GET/PATCH/DELETE /venue-saves/...`), `GET /users/{id}/lists`,
  `GET /users/{id}/venue-saves`, `GET /users/me/notifications`,
  `GET /users/me/notifications/unread-count`,
  `POST /users/me/notifications/read-all`.

**Why now:** depends on both USER (Phase 1) and CHECKIN (Phase 3) existing; the feed in Phase 16 depends on FOLLOW.

---

## Phase 5 — Schema Reconciliation & Account Lifecycle

Everything where the code shipped in Phases 1–4 contradicts the PDD as it
now stands, corrected in one breaking migration set. All of it has the same
single cause — the PDD grew substantially after those phases shipped — so it
is one phase, one release, one CHANGELOG entry, rather than a correction
scattered across the phases that happen to consume each field.

- **`USER` schema.** `display_name` added (shown everywhere, freely
  editable, no uniqueness constraint); `username` becomes the unique,
  non-null handle that search, mentions, and profile URLs key off of;
  `status` (`active` | `frozen` | `suspended`) added, kept deliberately
  separate from `role` — `role` is permission level, `status` is standing,
  and conflating them would be a mistake. Username edits are rate-limited:
  an unrestricted handle is an impersonation vector in a way a display name
  isn't (PDD §7).
- **The product layer is removed (ADR-0011).** `PRODUCT`,
  `GLOBAL_PRODUCT_TYPE` (+ its translation table), and `CHECKIN_PRODUCT`
  are dropped, along with their services, schemas, endpoints, seed data,
  and the `products` router registration. Applied migrations are never
  edited (see [CLAUDE.md](../CLAUDE.md)), so this is a new migration that
  drops them. At MVP volume no individual item could reach PDD §8's
  10-rating floor, so the two check-in steps this cost every user returned
  no label; what was eaten lives in `note` instead.
- **`CHECKIN` gains `rating_taste`, and all four criteria become
  required**, in the request schema and the DB constraints alike. Food
  quality lived entirely in `CHECKIN_PRODUCT.rating` until now — without
  this field a food platform would rate ambiance and service but never the
  food. `rating_value` keeps its column name and is redefined as value for
  money (Turkish label *Fiyat*, not *Değer*). The four-point scale in
  `app/core/ratings.py` is unchanged and stays — it now backs four fields
  instead of one.
- **Check-in creation stops requiring products.** `min_length=1` on the
  request schema and `EmptyProductListError` in the service both go, along
  with the duplicate-product and product-availability validations.
- **Foreign-key and delete policy.** Every column referencing `users.id` is
  reviewed against PDD §7's account-deletion semantics: personal content
  (check-ins and their likes/bookmarks/mentions, lists and their items,
  venue saves) is purged; `VENUE.added_by` becomes nullable with
  `ON DELETE SET NULL`, because a venue is a shared resource that outlives
  the account that added it, not personal content.
- **The Clerk `user.deleted` handler is repointed at that purge.** It
  currently issues a plain `DELETE` against `users`, written in Phase 1 when
  nothing referenced `users.id` yet, with a comment to revisit once
  check-ins and follows existed. They have existed since Phase 3, and no
  `users.id` foreign key declares an `ondelete` — so deleting a user with
  any content fails on a foreign-key violation, the webhook 500s, Clerk
  retries indefinitely, and the account stays in our database after being
  deleted at the provider. This is the one live runtime defect in the
  current codebase, and it is also a data-protection exposure, not just a
  crash.
- **Account lifecycle endpoints.** `PATCH /users/me` (display_name,
  username with its rate limit, bio, avatar_url, city, locale, timezone);
  `DELETE /users/me` — permanent purge, the one deliberate exception to
  "historical data is never deleted," required for store compliance (Apple
  §5.1.1(v) and Google Play's equivalent); `POST /users/me/freeze` —
  self-service and reversible, reactivated by simply logging back in,
  distinct from admin suspension.
- **`status` is enforced on every read path.** A frozen or suspended user
  drops out of listings and profile reads, and a suspended profile behaves
  exactly like a nonexistent one — the existence-leak standard Phase 4
  already established in `app.core.authz.ensure_visible_and_owned`, applied
  to accounts rather than content.
- **Hygiene carried by the same phase.** `app/services/checkin.py` and
  `app/services/list.py` are both over the 300-line limit this repo sets for
  itself; split them. Write the `README.md` the shared standards require and
  this repo doesn't have (setup, running, tests, env reference).

**Why now:** every later phase builds on this schema. Left until the phases
that consume each field, `USER` and `VENUE` get migrated repeatedly and each
correction gets tangled into an unrelated phase's rationale. This is also the
cheapest possible window for a breaking change: there is no production data
and no client yet, and that window closes the day `obur-web` or `obur-mobile`
starts.

**Deliberately not in this phase:** the `VENUE` drift (`status` →
`is_active`/`is_suspended`, `district`, `is_verified`). All three are parts of
one decision recorded in ADR-0009, and splitting them across two phases would
split that reasoning — they land together in Phase 9.

## Phase 6 — Catalog Read Surface & Localization

- **Category read endpoint.** `GET /api/v1/venue-categories`, hierarchical.
  It doesn't exist today: the seed data is written and the table is
  populated, but nothing exposes it, so a client can't build the category
  picker that venue creation needs (PDD §10 Step 1).
- **The category catalog is expanded.** It holds 9 entries — no meyhane,
  pizza, burger, kahvaltı, pastane, lokanta, or ice cream — and with the
  product layer gone `VENUE.category_id` is the platform's only
  classification dimension, read by three separate consumers (Discover
  filters, Phase 16's Layer-2 ranking signal, and Phase 13's personalized
  history, whose specificity depends on it entirely). Grow it toward
  ~30–40 leaves, drawing on a published external taxonomy rather than
  inventing one. This is seed data plus translations, not a migration, so
  it can land incrementally.
- **The translation tables get a read path.** `VENUE_CATEGORY_TRANSLATION`
  is seeded but never read by any service — the whole translation-table
  design is currently write-only.
  Resolution keys off the requesting user's `locale`, falling back to
  `DEFAULT_LOCALE` when a translation is missing, per PDD §7's
  "Translation tables over embedded strings" decision.
- `SUPPORTED_LOCALES` goes from `("tr",)` to `("tr", "en")` and
  `app/seeds/locales/en.py` is added — PDD §6 lists TR and EN as both being
  MVP, and a language the seeds don't cover isn't really supported.
- `VenueResponse` gains the resolved category name alongside the raw
  `category_id`.

**Why now:** this establishes the locale-resolution pattern once, before
there are three more translation tables to be inconsistent about — Phase 14's
`BADGE_TRANSLATION` inherits it rather than inventing a second approach. It
also unblocks two client screens that no later phase would otherwise cover.

## Phase 7 — Cross-Cutting Guardrails

The mechanisms behind the [Standing Rules](#standing-rules) above, built once
against the endpoint surface that already exists. From here on, each phase
applies them rather than deferring them.

- **Redis-backed rate limiting** (`app/middleware/`), per
  [ADR-0014](https://github.com/oburapp/obur-docs/blob/main/adr/0014-rate-limiting-keys-and-ip-minimisation.md).
  Authenticated callers key on `user_id`, anonymous ones on an HMAC of the
  client address resolved rightmost-ish from `X-Forwarded-For` — the
  obvious leftmost reading lets an attacker spoof a fresh key per request
  and evade the limiter entirely. Fixed-window counter, chosen over a more
  precise sliding window because address-derived keys let an attacker
  control key count. Baseline tier on every endpoint; strict tier on
  check-in creation, report submission, venue creation, and follow. On
  counter-store failure the tiers diverge: strict fails closed, baseline
  fails open. Trusted proxy count is configuration with no default and is
  verified against the real topology in Phase 8.
- **Error contract**, per
  [ADR-0015](https://github.com/oburapp/obur-docs/blob/main/adr/0015-error-contract-and-request-correlation.md).
  RFC 9457 Problem Details on every error path including FastAPI's own
  validation failures, with `type` as the discriminator — two conditions
  already share `429` and no other status fits either. `str(exception)`
  stops reaching responses at roughly fifteen call sites, each of which
  needs a real user-facing string written for it.
- **Request correlation and structured logging.** `X-Request-ID` generated
  per request, echoed back, on every log line; an inbound value is honoured
  only if it validates, since an unvalidated one is a log-injection vector.
  JSON logs excluding OWASP's list plus the raw client address and
  rate-limit key. `traceparent` is deferred with recorded revisit
  conditions (ADR-0015).
- **Latency instrumentation.** PDD §17 sets P50 < 200ms / P90 < 500ms /
  P99 < 1s for standard reads, with check-in creation deliberately exempt.
  A target that isn't measured can't be met; the duration lands on the log
  line above, and where those numbers are aggregated is a Phase 8 decision
  once the platform's own facilities are known.
- Pagination audit across every existing list endpoint, `GZipMiddleware`,
  and graceful shutdown in `lifespan` (dispose the engine, close HTTP
  clients). The audit found twelve of thirteen list endpoints already
  capped; the exception is the category catalog, which is served whole on
  purpose — it is a tree, and half a tree is a broken picker rather than a
  shorter list. Its bound is `MAX_CATALOG_SIZE`, enforced by a test, so the
  exception stays a decision instead of becoming an oversight.

**Why now:** these apply to everything, so they cost the least when the
endpoint surface is smallest — and every phase after this one inherits them
for free. Deferring cross-cutting work to a single late phase is precisely
what produced the drift this roadmap was rewritten to correct.

**This phase grew during design, deliberately.** Settling the error
contract surfaced that ~15 endpoints leak exception text to clients, and
fixing that is a change to every error path rather than an addition beside
them. Shipping a contract half the endpoints don't follow would have been
the cheaper and worse option.

**Two live defects surfaced while building it**, both of the same kind —
code that read a value which was not there yet, and degraded silently
rather than failing:

- *The strict rate-limit tier never applied.* The tier was read from
  `scope["route"]`, which Starlette populates only once the router runs —
  after all middleware. Every strict route was metered at the baseline
  600/hour instead of 30, and failed *open* rather than closed when the
  counter store was unavailable. Routes are now matched against templates
  the limiter declares itself, pinned to real routes by a test, because the
  cost of that list drifting is the same silent failure again.
- *Alembic disabled the application's loggers.* `fileConfig` defaults to
  `disable_existing_loggers=True`, which is harmless in its own process and
  not harmless in-process: after the suite migrated, nothing in `app/`
  logged anything. Both defects argue the same thing — a guardrail that
  fails quietly is worse than none, because it is believed.

**Moved out of this phase, deliberately:** Row Level Security, to Phase 8.
It was here on the reasoning that all cross-cutting work belongs together,
but its first requirement is a database role that isn't the table owner —
PostgreSQL exempts owners from RLS, so policies written against the current
single-role setup would silently enforce nothing. That role split is
deployment configuration, and PDD §17 itself groups RLS with the
infrastructure isolation layer rather than with application middleware.

## Phase 8 — Deployment & Database Isolation

- `Dockerfile` (part of the target layout, not yet written), Railway service
  plus PostgreSQL and Redis in the same region, and `docs/deployment.md`
  written against the real setup rather than a guess.
- **Register the Clerk webhook against the deployed URL.** Open since
  Phase 1 for want of a public URL; `CLERK_WEBHOOK_SECRET` moves from an
  empty-string sentinel to a required setting in the same change that starts
  depending on it.
- **Set `authorized_parties` (the `azp` claim check)** to the real
  `obur-web` / `obur-mobile` origins — also deferred since Phase 1.
- **Close PDD §18's infrastructure research item:** confirm whether Railway's
  PostgreSQL is encrypted at rest and whether it is reachable only from the
  backend service or from the outside. PDD §17 is explicit that `can_view` is
  application code and protects only the application's own access path; this
  is the separate layer, and it is a hosting fact to be verified, not
  assumed. Record the answer where the question was asked.
- Fill in [runbooks/incident-response.md](https://github.com/oburapp/obur-docs/blob/main/runbooks/incident-response.md)
  against the real deployment — it is currently a stub.
- **Two database roles.** An owner role for migrations and the seeder, and a
  separate application role the API connects as. This is the prerequisite
  for everything below it: PostgreSQL exempts a table's owner from that
  table's row-level policies, so an application connecting as the owner —
  which is the setup today — would have policies that silently enforce
  nothing. `FORCE ROW LEVEL SECURITY` on a single role was considered and
  rejected: it would filter the seeder too, and an owner can turn
  `row_security` off, meaning a compromised application could disable its
  own protection.
- **Row Level Security across every table.** PDD §17 names it as the
  concrete mechanism for the second layer this phase is otherwise about —
  the one that survives a query forgetting to call `can_view`, which is the
  exact failure behind two real bugs already found on this project.
  Requires, beyond the roles above:
  - Per-transaction identity. Policies read `current_setting`, so the
    current user id is set with `SET LOCAL` at the start of every
    transaction — not once per connection (pooling) and not once per
    request, since services commit mid-request and a commit ends the
    transaction the setting was scoped to.
  - An enumerated bypass list: migrations, the seeder, admin moderation
    tooling, and Phase 14's platform-wide badge `rarity_pct`.
  - An ADR covering the cost this accepts. A policy re-expresses `can_view`
    in SQL, so one rule now has two implementations that can drift from
    each other — a new version of the very failure RLS exists to catch. The
    ADR records how they are kept in step.
  - Test fixtures that create rows directly rather than through services
    (most of the integration suite) have to run under a role and policy set
    that permits it, or the suite tests nothing.

**Why now:** two security gaps (the unregistered webhook, the unset `azp`
check) can only be closed with a live public URL, and the latency targets
from Phase 7 can only be measured in a real environment. There is no
production data yet, so the breaking migrations in later phases still carry
no migration risk — and every phase from here deploys continuously instead of
saving up one high-risk cutover at the end.

**Why RLS here rather than earlier:** its prerequisite is a role split,
which is deployment configuration, and managed Postgres providers differ in
what role management they permit. Building it against docker-compose and
then rebuilding it against the real instance is the same work twice, with
the second attempt the one that can surprise. Doing it here also restores
the posture PDD §17 actually asked for — every query from Phase 9 onward is
written with RLS already on, rather than retrofitted again later.

**The cost of this ordering, stated plainly:** there is no second layer
until this phase lands. Accepted because `can_view` and
`ensure_visible_and_owned` are centralised and consistently used today, and
because the alternative is building the mechanism twice.

## Phase 9 — Venue Discovery Enrichment

Implements [ADR-0009](https://github.com/oburapp/obur-docs/blob/main/adr/0009-venue-discovery-enrichment.md)
in full, including the `VENUE` drift held back from Phase 5. That ADR carries
the reasoning for every item here.

- `VENUE.district`, required for venues created from here on, nullable for
  earlier rows, no backfill.
- `VENUE.status` becomes `is_active` + `is_suspended`, both admin-only, and
  comes off `VenueResponse` — a breaking contract change that costs nothing
  before a client exists.
- No venue field is user-editable; corrections are report-driven (Phase 10).
- `google_places_id` partial unique index, and two-layer duplicate
  detection: an exact Google match resolves idempotently and cannot be
  overridden with `confirm_duplicate`.
- `VENUE.is_verified`, cosmetic only, on named-constant thresholds.

**Why now:** `district` gates Phase 16's district-scoped ranking and Phase
14's geography badges. Zero external dependencies — the backend never calls
Google, it stores what the client already resolved.

**Deferred, on purpose:** a backend-proxied Geocoding endpoint. Separate
work with its own secret and outbound dependency, and it blocks nothing —
manual venue entry works from a map pin. See [Out of Scope](#out-of-scope).

## Phase 10 — Safety: Blocking, Mute & Reporting

Schema from [ADR-0010](https://github.com/oburapp/obur-docs/blob/main/adr/0010-blocking-and-reporting-schema.md);
behaviour from PDD §11.

- `BLOCK`, `MUTE`, `CONTENT_REPORT`, `VENUE_REPORT`.
- **`can_view` gains a blocking dimension**, overriding all three visibility
  tiers including `public`. Every listing query from Phases 3–4 gains the
  filter, reusing the `close_friend_of_owner_exists` correlated-subquery
  pattern so it stays one query.
- Blocking semantics per PDD §11: bidirectional auto-unfollow, mutual
  disappearance, silent, retroactive purge of likes/bookmarks/notifications,
  per-viewer anonymisation. Unblocking restores nothing.
- Mute: one-directional, silent, feed-only, not derived from `FOLLOW`.
- Reporting on check-in, profile, and venue. No automatic threshold-based
  hiding — coordinated false reporting is itself an abuse vector.
- `app/api/v1/admin.py` becomes a real moderation surface: report queue,
  dismiss, content removal, `USER.status`, both venue booleans.

**Why now:** blocking is a cross-cutting authorization primitive like
visibility. Phase 13's first discoverer, Phase 15's signed URLs, and Phase
16's feed all have to be viewer-aware, and retrofitting after the read-heavy
phases would not be as cheap as Phase 4's `is_public` → `visibility` was.
Also P0 for store review (Apple §1.2, Google Play UGC).

## Phase 11 — Check-in Reliability: Drafts & Idempotency

Both tables are specified in PDD §7, including why a draft is its own table
rather than a `CHECKIN.is_draft` flag.

- `CHECKIN_DRAFT` plus CRUD, server-synced so a draft started on mobile
  resumes on web; promoted to a real `CHECKIN` on submit, then deleted.
- `CHECKIN.idempotency_key` with `UNIQUE (user_id, idempotency_key)`; a
  retried submission returns the original rather than creating a second.

**Why now:** PDD §17 classes this as an MVP requirement. The mobile client's
retry-on-reconnect guarantee rests on the idempotency key, so the API side
has to exist before client work starts.

## Phase 12 — Mentions & Hashtags

- `CHECKIN_MENTION` as a structured table rather than text parsed from
  `note`, so creation, notification, and block-time purge are enforceable.
  Mutual-follow only; never overrides visibility.
- `HASHTAG`, `CHECKIN_HASHTAG`, `LIST_HASHTAG`, five per item.
- **Turkish-aware normalisation, not `lower()`.** Dotted/dotless İ-I splits
  one tag across two rows — the same class of bug ADR-0007 found with
  `COLLATE "C"`.
- Hashtag discovery over `public` content; `NotificationType` gains
  `mention`.

**Why now:** the mutual-follow requirement and the block-time purge both
depend on Phase 10.

## Phase 13 — Aggregate Scoring & Personalized History

The procedure is PDD §8, rewritten twice since the original roadmap line —
first replacing a band table with a statistical one, then collapsing to a
single level when [ADR-0011](https://github.com/oburapp/obur-docs/blob/main/adr/0011-drop-product-layer-four-venue-criteria.md)
removed the product layer.

- One score, at venue level, pooling all four criteria from `public`,
  non-soft-deleted check-ins. No second level; the product-level score left
  with the product layer.
- Below a 10-rating floor, no label. Above it, the 95% confidence lower
  bound placed in PDD §8's 9-tier band table. Only the label is shown.
- **The four criteria are also exposed individually** on a venue page — a
  venue with excellent food and poor value is exactly what one averaged
  number hides. *No ADR yet; write one when this phase starts.*
- Personalized "best per category" history on a user's own profile. A read
  query over existing data, and the only thing here with **no volume floor**
  — it reports the user's own rating, not a platform statistic.
- Band cut points and the floor are named constants, so PDD §18's
  calibration item is a value change.

**Why now:** depends on Phase 5's four required criteria and Phase 6's
expanded catalog; Phase 16's Discover ranking consumes the score.

## Phase 14 — Badges

Permanence and its architectural consequence — forward-only synchronous
evaluation, no re-scan job — are settled in PDD §6.

- `BADGE`, `BADGE_TRANSLATION`, `USER_BADGE`, following Phase 6's
  locale-resolution pattern.
- Admin-only manual revocation as the single exception, for fraud.
- `rarity_pct` is the one thing needing a scheduled job, since it is a
  percentage over the whole user base. The only periodic job in the system;
  its cadence is a named constant.
- `NotificationType` gains `badge_earned`; the check-in creation response
  reports newly earned badges and first-discoverer status, which is what
  PDD §17's celebration moments need from the API.

**Why now:** built on `visited_at` / `visited_tz` (Phase 3) and `district`
(Phase 9). The evaluation-trigger architecture is decided here on its own
terms, across the full variety of badge conditions — deliberately not
generalised from Phase 9's much narrower check-in-count trigger.

## Phase 15 — Media Pipeline

Applies to the two upload surfaces that exist, `CHECKIN.photo_url` and
`USER.avatar_url`. A venue has no upload surface, and a list has no cover.

- R2 upload; `R2_*` settings move from empty-string sentinels to required in
  the same change that starts using them.
- JPEG / PNG / HEIC / WebP, HEIC converted server-side, no animated formats;
  a ~15MB server-side cap as an abuse net.
- **All EXIF stripped, not just GPS** (PDD §17). Device model and precise
  timestamps are identifying in their own right.
- Multiple resolutions per upload; avatars cropped square, check-in photos
  keeping their aspect ratio.
- **Signed URLs for `close_friends` and `private` photos only**, generated
  after `can_view` passes. A check-in's visibility is enforced on its row,
  but the photo sits in R2 and is reachable directly if the URL escapes.
  Public photos and avatars stay unsigned — nothing is left to enforce, and
  signing would cost CDN cacheability for nothing.
  *No ADR yet; write one when this phase starts.*
- Orphaned objects cleaned up on row deletion; processing runs via
  `asyncio.run_in_executor`.

**Why now:** the signed-URL decision depends on Phase 10's completed
visibility-and-blocking model, and Phase 16 consumes real uploaded images.

## Phase 16 — Feed & Discovery

Feed layers, ranking signals, and their priority order are PDD §12.

- Two-layer main feed; Layer 2 engages when Layer 1 falls below a threshold
  of the feed. **Both layers take mute and block as query inputs**, not as a
  filter applied afterward. Algorithmic items are flagged in the response.
- Discover across four types — venue, user, list, and **hashtag**, which the
  original roadmap's discovery line did not cover. City filter doubles as
  travel mode's manual selector.
- Discover ranking per PDD §12, with recency breaking ties.
- **A venue's representative photo is derived, never uploaded** — its
  most-liked `public` check-in photo, computed at read time so it is always
  current with no invalidation to get wrong, and selected **per viewer** so
  a blocked pair each sees the next eligible photo. Scoped to blocking, not
  muting. *No ADR yet; write one when this phase starts.*
- "First discoverer" on a venue page, with the same per-viewer
  anonymisation.

**Why now:** ranking signals come from Phase 13, exclusions from Phase 10,
imagery from Phase 15. The most dependency-laden surface in the PDD, which
is why it is last among the feature phases.

## Phase 17 — Notification Preferences & PDD Coverage Audit

- Per-trigger notification opt-out (follow, check-in like, list like, badge,
  mention) — storage plus enforcement at every notification write path. It
  sits here because every type only exists as of Phase 14.
- Recent likes activity view across check-ins and lists (PDD §5).
- **A full PDD coverage audit.** Every row of §6, every table in §7, every
  requirement in §17, checked against what exists. Anything missing is built
  here or moved to [Out of Scope](#out-of-scope) with a reason. The
  [PDD Coverage Matrix](#pdd-coverage-matrix) reaches its final state as the
  output.

**Why now:** this phase is the evidence for the roadmap's central claim —
that client work can start without anyone coming back to the backend. Worth
auditing deliberately rather than assuming.

## Phase 18 — Release 1.0.0

- Full integration pass: auth, check-in creation, venue search, feed,
  moderation.
- The 98% coverage bar and N+1 query-count tests verified across every list
  endpoint, not just the ones that had them first.
- `[Unreleased]` becomes `[1.0.0]`, `pyproject.toml` matches, and a human
  tags `v1.0.0` per the shared release process.
- What 1.0.0 means: the API contract is stable enough for `obur-web` and
  `obur-mobile` to build against.

**Explicitly not in scope:** load and performance testing. The MVP target is
200 MAU; there is no real traffic pattern to test against yet. Revisit if
that target changes.

---

## Out of Scope

Things the PDD discusses that this roadmap deliberately does not build, so
the coverage claim above can be checked rather than taken on trust.

**Deferred by the PDD itself, pending a trigger:**

- **A backend-proxied Geocoding endpoint** (free-text address → approximate
  coordinate). Deferred by ADR-0009: a new third-party secret, a new
  outbound HTTP dependency, its own failure modes and cost monitoring. It
  blocks no client work — manual venue entry works from a map pin. Gets its
  own ADR when prioritized.
- **Meilisearch migration.** PDD §18: only once `pg_trgm` hits a real
  performance wall, documented as an ADR at that point.
- **Fraud and fake-account tooling** — phone verification, self-built SMS
  OTP, IP correlation. PDD §17 sets each aside for a concrete reason and
  defers all of them until real abuse is observed rather than building
  pre-emptively against a hypothetical.

**v2.0, not MVP:** the "You Might Like" shelf, profile suggestions, and
expansion to a second city.

**Client-side, not backend work:** dark mode, share cards, map rendering,
Google Places Autocomplete, accessibility, haptic feedback, and the local
interaction-feedback and celebration behavior in PDD §17. The backend's part
of celebration — reporting a newly earned badge and first-discoverer status —
is in Phase 14.

**Needs a lawyer, not an engineer:** the Content Policy text, Terms of
Service, and Privacy Policy; Turkish "sosyal ağ sağlayıcı" obligations under
Law 5651 / 7253; and the GDPR-alongside-KVKK question. The published
support/abuse contact and the pages that host this text are client and store
listing concerns (PDD §11, §18).

---

## PDD Coverage Matrix

### Feature catalog (PDD §6)

| Feature | Phase |
|---|---|
| Sign up / sign in | 1 |
| Edit profile | 5 |
| Delete account | 5 |
| Freeze account | 5 |
| Follow users | 4 |
| Block users | 10 |
| Report content / accounts / venues | 10 |
| Create check-in | 3, drafts in 11 |
| Feed | 16 |
| Discover | 16 |
| Venue page | 13 (score + four criteria), 16 (photo, first discoverer) |
| Profile | 4, 13, 14 |
| Badge system | 14 |
| List creation | 4 |
| Save venue | 4 |
| Close friends | 4 |
| Mute users | 10 |
| Like | 4 |
| Bookmark | 4 |
| Map view | Client — venue coordinates already exposed |
| Notifications | 4; `mention` in 12, `badge_earned` in 14 |
| Visibility control | 4 |
| Travel mode | 16 (city filter) |
| Venue verification | 9 |
| Support / abuse contact page | Out of scope — client + store listing |
| Content Policy / Terms / Privacy pages | Out of scope — client + legal |
| Notification preferences | 17 |
| Dark mode | Out of scope — client |
| Language switching | 5 (`locale` write), 6 (resolution) |
| Recent likes view | 17 |
| @ Mentions | 12 |
| # Hashtags | 12 |
| Personalized history | 13 — keyed on `VENUE.category_id`, not product type |
| Share cards | Out of scope — client |

### Data model (PDD §7)

| Table | Phase |
|---|---|
| `USER` | 1; `display_name` / `username` / `status` in 5 |
| `FOLLOW`, `CLOSE_FRIEND` | 4 |
| `MUTE` | 10 |
| `BLOCK`, `CONTENT_REPORT`, `VENUE_REPORT` | 10 — schema per ADR-0010 |
| `VENUE_CATEGORY` (+ translation) | 2; read path and catalog expansion in 6 |
| `VENUE` | 2; `district` / `is_verified` / `is_active` / `is_suspended` in 9 |
| `VENUE_SAVE` | 4 |
| ~~`GLOBAL_PRODUCT_TYPE`~~, ~~`PRODUCT`~~ | Built in 2, **dropped in 5** — ADR-0011 |
| `CHECKIN` | 3; `rating_taste` + four required criteria in 5, `idempotency_key` in 11 |
| `CHECKIN_DRAFT` | 11 |
| ~~`CHECKIN_PRODUCT`~~ | Built in 3, **dropped in 5** — ADR-0011 |
| `CHECKIN_LIKE`, `CHECKIN_BOOKMARK` | 4 |
| `CHECKIN_MENTION` | 12 |
| `HASHTAG`, `CHECKIN_HASHTAG`, `LIST_HASHTAG` | 12 |
| `LIST`, `LIST_ITEM`, `LIST_LIKE`, `LIST_BOOKMARK` | 4 |
| `NOTIFICATION` | 4; preferences in 17 |
| `BADGE`, `BADGE_TRANSLATION`, `USER_BADGE` | 14 |

### Non-functional requirements (PDD §17)

| Requirement | Phase |
|---|---|
| Offline & draft reliability | 11 |
| Rate limiting (baseline + strict tiers) | 7, then per-phase via Standing Rules |
| Fake-account resistance tooling | Out of scope — deferred until abuse is observed |
| Bulk-extraction resistance | 7 |
| Signed URLs for private photos | 15 |
| Governing principle / RLS | 8 (role split, policies, infrastructure layer) + Standing Rules from there on |
| Photo upload standards | 15 |
| API latency targets | 7 (instrumentation), 8 (real environment) |
| Local interaction feedback, celebration | Out of scope — client; badge/first-discoverer payload in 14 |
| No numeric uptime target at MVP | Accepted as stated; 8 |

### Open decisions (PDD §18)

| Decision | Phase |
|---|---|
| Aggregate rating threshold calibration | 13 — named constants, value change not code change |
| Badge rarity calculation period | 14 |
| Database encryption at rest / network isolation | 8 |
| RLS policies, table by table | 8 + Standing Rules from there on |
| "You Might Like" activation volume | Out of scope — v2.0 |
| TRY pricing, second-city timing | Out of scope — not engineering work |
| Meilisearch migration threshold | Out of scope — deferred |
| Fraud detection tooling | Out of scope — deferred |
| Accessibility | Out of scope — client |
| Legal research items | Out of scope — needs a lawyer |
