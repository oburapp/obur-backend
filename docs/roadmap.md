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

Version numbering follows the pattern already established (Phase 0 → `0.1.0`,
Phase 4 → `0.5.0`): each phase is cut as a minor release, `Phase N → 0.(N+1).0`,
through Phase 17 → `0.18.0`, then `1.0.0` at Phase 18.

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
   moderation tooling, cross-user ranking). Deciding this while the query is
   being written is far cheaper than re-auditing later (PDD §17).
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

- **Row Level Security, retrofitted across the existing tables.** PDD §17
  names RLS as the concrete second layer behind the governing principle —
  the only way to reach data is through the application's own authorization
  logic — and specifically frames it as development-time discipline rather
  than a retrofit project. Phases 0–4 shipped with none, so a single focused
  pass is now unavoidable; doing it here rather than later keeps it to one
  pass. The access patterns that legitimately need to see across users
  (platform-wide counts, cross-venue ranking, admin moderation tooling) are
  enumerated explicitly as bypasses, with reasons, rather than discovered one
  at a time later.
- **Redis-backed rate limiting** (`app/middleware/`). A baseline tier on
  every public endpoint, and a strict tier on the four actions PDD §17
  identifies as doing real damage under repeated abuse: check-in creation
  (direct aggregate-rating manipulation, an attack on the platform's core
  credibility), report submission (coordinated false reporting), venue
  creation (spam venues), and follow. **Read endpoints are rate-limited
  too** — Discover, search, and venue listing are exactly what a scraper
  enumerates, and PDD §17's bulk-extraction resistance depends on the
  combination of a read limit and a capped page size.
- **Error contract and structured logging.** A request id on every request,
  one consistent error body shape, no stack traces or internal detail
  reaching a client, nothing sensitive reaching the logs.
- **Latency instrumentation.** PDD §17 sets P50 < 200ms / P90 < 500ms /
  P99 < 1s for standard reads, with check-in creation deliberately exempt.
  A target that isn't measured can't be met, and this is where the
  measurement comes from.
- Pagination audit across every existing list endpoint, `GZipMiddleware`,
  and graceful shutdown in `lifespan` (dispose the engine, close HTTP
  clients).

**Why now:** these apply to everything, so they cost the least when the
endpoint surface is smallest — and every phase after this one inherits them
for free. Deferring cross-cutting work to a single late phase is precisely
what produced the drift this roadmap was rewritten to correct.

## Phase 8 — Deployment & Live Environment

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

**Why now:** two security gaps (the unregistered webhook, the unset `azp`
check) can only be closed with a live public URL, and the latency targets
from Phase 7 can only be measured in a real environment. There is no
production data yet, so the breaking migrations in later phases still carry
no migration risk — and every phase from here deploys continuously instead of
saving up one high-risk cutover at the end.

## Phase 9 — Venue Discovery Enrichment

Implements ADR-0009 in full, including the `VENUE` drift deliberately held
back from Phase 5.

- **`VENUE.district`** (ilçe / sub-city administrative area) — required for
  every venue created from here on, whichever path created it; nullable only
  for rows that predate this phase, with no backfill planned. `city` alone
  cannot express "Kadıköy" as a scope for discovery, rankings, or badges.
- **`VENUE.status` is replaced by `is_active` and `is_suspended`**, two
  independent admin-only booleans. `is_active = false` is a closed business:
  the venue stays fully visible, shown transparently as inactive.
  `is_suspended = true` is a moderation action: the venue is hidden
  entirely and its own page returns a generic "not found," never an
  explanation — the same "hidden must be indistinguishable from nonexistent"
  standard applied to private check-ins and blocked profiles. `status` also
  comes off `VenueResponse`, which is a breaking contract change that costs
  nothing today and would cost real client work after Phase 18.
- **No venue field is ever directly user-editable**, including by whoever
  added it. Every correction is report-driven and admin-only (Phase 10),
  on the abuse precedent recorded in ADR-0009.
- **`google_places_id` gains a partial unique index** (`WHERE ... IS NOT
  NULL`) — two venues can no longer carry the same Google identity.
- **Two-layer duplicate detection in `create_venue`.** An exact
  `google_places_id` match is a certain duplicate and resolves to the
  existing venue idempotently, with no prompt and **no** `confirm_duplicate`
  bypass — there is nothing to confirm. The existing 50m `ST_DWithin` check
  remains the fallback for everything else and stays user-confirmable.
- **`VENUE.is_verified`** — cosmetic only, never affecting ranking, search,
  or discoverability. Set when either `google_places_id` is present and at
  least `N` distinct users have checked in, or, with no `google_places_id`,
  at least `M` distinct users have checked in **and** an admin has confirmed
  it through a new admin-only endpoint. Only `public`, non-soft-deleted
  check-ins count toward `N`/`M`, the same restriction the aggregate rating
  applies and for the same reason. Evaluated synchronously as one extra
  count query during check-in creation; no notification is sent. `N` and `M`
  are named constants.

**Why now:** `district` gates Phase 16's district-scoped venue ranking and
Phase 14's geography-scoped badges. The phase has zero external dependencies
— the backend never calls Google, it only stores what the client already
resolved — so it carries none of the risk a real integration would.

**Deferred from this phase, on purpose:** a backend-proxied Geocoding
endpoint (free-text address → approximate coordinate). It is genuinely
separate work — a new third-party secret, a new outbound HTTP dependency, its
own failure modes and cost monitoring — and it blocks nothing, since manual
venue entry works from a map pin. See [Out of Scope](#out-of-scope).

## Phase 10 — Safety: Blocking, Mute & Reporting

**Schema defined by ADR-0010 in obur-docs.** Blocking and reporting are both
P0 and both specified at length in PDD §11, but until ADR-0010 neither had a
table in PDD §7 or in the ER diagram — the mechanism was fully described in
prose with no schema anywhere, which is what left this phase with nothing to
build against. ADR-0010 settled it, along with the matching PDD §7 and ER
updates: `BLOCK` stores direction and enforces in both, and reports split
into `CONTENT_REPORT` and `VENUE_REPORT` — two tables by concern rather than
one polymorphic table or three by target, so `VENUE_REPORT` can keep a real
foreign key while `CONTENT_REPORT` deliberately doesn't.

- `BLOCK`, `MUTE`, `CONTENT_REPORT`, and `VENUE_REPORT`, per ADR-0010.
- **`can_view` gains a blocking dimension.** Blocking overrides all three
  visibility tiers, `public` included — it is not another tier a viewer can
  be excluded from. Every listing query written in Phases 3–4 (check-ins,
  lists, venue saves, bookmarks of either, followers, following,
  notifications) gains the block filter, reusing the existing
  `close_friend_of_owner_exists` correlated-subquery pattern so it stays one
  query rather than a per-row lookup.
- **Blocking semantics** (PDD §11): auto-unfollow in both directions
  (`CLOSE_FRIEND` already cascades off `FOLLOW`, so close-friend status is
  revoked for free); mutual disappearance from search and Discover; silent,
  with a blocked profile behaving exactly like a nonexistent one;
  retroactive purge of likes, bookmarks, and notifications between the two
  people in both directions; and per-viewer anonymization wherever one
  person's identity would otherwise surface on something the other can see
  ("first discoverer"), which changes display, not data. Unblocking restores
  nothing automatically.
- **Mute**, the lighter counterpart: one-directional, silent, and scoped to
  feed display only. Not derived from `FOLLOW` — a user can mute someone
  they don't follow. No retroactive effect of any kind.
- **Reporting** across three target types — check-in, profile, venue — with
  interpersonal-safety reasons for the first two and data-quality reasons
  for the third. Deliberately **no automatic threshold-based hiding**:
  coordinated false reporting is itself a known abuse vector, and at this
  scale human review doesn't have a throughput problem.
- **A real admin moderation surface.** Report queue listing, dismiss, remove
  content, `USER.status = suspended`, and `VENUE.is_active` /
  `is_suspended` — the only path by which either venue boolean ever flips.
  `app/api/v1/admin.py` currently holds a single endpoint; this is where it
  becomes a moderation surface. Admin access is never affected by a block
  between two other users.

**Why now:** blocking is a cross-cutting authorization primitive, in the same
category as visibility. Phase 13's "first discoverer," Phase 16's derived
venue photo, and Phase 16's feed all have to be viewer-aware. Phase 4's
`is_public` → `visibility` retrofit was cheap because only Phase 3 existed;
retrofitting blocking after the read-heavy phases would not be. It is also
P0 for store review — without a working block and report mechanism the app
does not clear Apple §1.2 or Google Play's UGC policy.

## Phase 11 — Check-in Reliability: Drafts & Idempotency

- **`CHECKIN_DRAFT`** — a separate table, deliberately not an `is_draft` flag
  on `CHECKIN`. A flag would require every aggregate, badge, and feed query
  to remember to filter it out forever, and this codebase has already hit
  that exact failure mode twice. A separate table makes a draft leaking into
  those queries structurally impossible rather than a matter of discipline.
  Server-synced, not device-local, so a draft started on mobile resumes on
  web — the same cross-device standard `NOTIFICATION.read_at` already set.
- Draft CRUD, and promotion to a real `CHECKIN` on submit, after which the
  draft row is deleted.
- **`CHECKIN.idempotency_key`** with `UNIQUE (user_id, idempotency_key)`. A
  retried submission with the same key returns the original check-in instead
  of creating a second one — this is what actually prevents a flaky
  connection from corrupting aggregate ratings and badge counts with
  duplicates.
- Nothing partially submitted is ever visible as a real check-in to anyone.

**Why now:** PDD §17 classes this as an MVP requirement, not a client-side
nicety — check-in is the core action, it takes real effort across five steps,
and venue interiors are exactly where a mobile connection is weakest. The
mobile client's automatic retry-on-reconnect guarantee rests entirely on the
idempotency key, so the API side has to exist before client work starts.

## Phase 12 — Mentions & Hashtags

- **`CHECKIN_MENTION`** — a structured table, not text parsed out of
  `CHECKIN.note` at render time, so creation, the notification it triggers,
  and its retroactive purge on blocking can all be enforced the way
  `CHECKIN_LIKE`'s are. Creatable only between mutual followers: tagging a
  stranger would reintroduce exactly the unwanted-attention vector the
  no-comment/no-DM stance exists to avoid. A mention notifies but **never**
  overrides the check-in's own visibility — extending access that way would
  be a backdoor around the authorization system kept airtight everywhere
  else.
- **`HASHTAG`, `CHECKIN_HASHTAG`, `LIST_HASHTAG`** — free text, no
  relationship requirement (a hashtag doesn't target a person), capped at 5
  per check-in or list at the application layer to keep hashtag discovery
  meaningful.
- **Turkish-aware normalization of `HASHTAG.tag`**, not a naive lowercase.
  Turkish's dotted/dotless İ-I distinction means a locale-naive case-fold
  silently produces two rows for what should be one tag — the same class of
  subtle text bug that `LIST_ITEM.position`'s `COLLATE "C"` requirement
  already caught in ADR-0007.
- A hashtag discovery endpoint listing every `public` check-in and list
  carrying it, most recent first — the same public-only scoping applied
  everywhere content is surfaced beyond its original audience.
- `NotificationType` gains `mention`.
- No new moderation path for either: an offensive hashtag or mention is part
  of the check-in or list it's attached to, already reportable as that
  content (Phase 10).

**Why now:** the mutual-follow requirement and the block-time purge both
depend on Phase 10's blocking semantics already existing.

## Phase 13 — Aggregate Scoring & Personalized History

PDD §8 was rewritten twice after the original roadmap line for this phase
was written — first replacing a band table with a statistical procedure, then
collapsing to a single level when the product layer was removed (ADR-0011).
What follows is the current shape, and it is considerably smaller than what
this phase originally carried.

- **One score, at the venue level.** Pool: every `rating_taste` /
  `rating_service` / `rating_ambiance` / `rating_value` value from every
  `public`, non-soft-deleted check-in at that venue. There is no second
  level and no separate pure-food score — the product-level score and the
  cross-venue item ranking it sorted both left with the product layer.
- **The procedure:** below a floor of 10 ratings, no label at all
  (*New / Low Data*); otherwise a 95% confidence lower bound on the mean,
  `x̄ − t(0.95, n−1) × (s / √n)`, clipped to [1.0, 4.0], placed in the
  9-tier symmetric Favorable/Unfavorable band table. Only the label is ever
  shown — never the raw score or the math — alongside the check-in count
  behind it.
- **The four criteria are also exposed individually** on a venue's page. A
  venue with excellent food and poor value is exactly what a single averaged
  number hides, and being able to say that is the whole reason four separate
  criteria exist.
- **Personalized "best of" history** on a user's own profile: their single
  highest-rated venue per `VENUE.category_id` ("en iyi dönerci: Develi"). A
  read query over existing data, no new tables. Unlike everything else in
  this phase it needs **no volume floor** — it reports the user's own
  rating, not a platform statistic, so it works from their first check-in.
  Its specificity depends entirely on how granular Phase 6 left the category
  catalog.
- Band cut points and the volume floor are named constants in one place, so
  PDD §18's calibration item is a value change rather than a code change.

**Why now:** depends on Phase 5's four required criteria and Phase 6's
expanded category catalog; Phase 16's Discover ranking consumes the venue
score.

## Phase 14 — Badges

- `BADGE`, `BADGE_TRANSLATION`, `USER_BADGE`, following Phase 6's
  locale-resolution pattern.
- **Permanent once earned, never automatically revoked**, even if the
  earning condition later becomes false. A badge documents something that
  happened, not something currently true. This removes an entire class of
  architecture: evaluation is **forward-only and synchronous**, checked at
  the moment an action might newly cross a threshold, with no re-scan job
  and no queue.
- Admin-only manual revocation is the single exception, for a badge resting
  on fraudulent activity.
- **`rarity_pct` is the one thing that genuinely needs a scheduled job** —
  it is a percentage over the entire user base, which doesn't recompute
  per profile view the way a per-check-in threshold check does. This is the
  only periodic job in the system; its cadence is a named constant.
- `NotificationType` gains `badge_earned`. The check-in creation response
  reports any newly earned badge and whether the check-in made its author a
  venue's first discoverer — PDD §17 reserves celebration for exactly these
  moments, and the client can only render them if the API says so.

**Why now:** built on `visited_at` / `visited_tz` from Phase 3 and `district`
from Phase 9. The evaluation-trigger architecture is decided here on its own
terms, across the full variety of badge conditions — deliberately not
generalized from Phase 9's much narrower check-in-count trigger.

## Phase 15 — Media Pipeline

Applies uniformly to the two upload surfaces that exist: `CHECKIN.photo_url`
and `USER.avatar_url`. A venue has no upload surface, and a list has no cover
image.

- R2 upload; the `R2_*` settings move from empty-string sentinels to
  required, in the same change that starts using them.
- Accepted formats JPEG / PNG / HEIC / WebP, with HEIC converted server-side
  to a web-standard format; no animated formats.
- **All EXIF metadata stripped on upload, not just GPS.** Device model,
  precise timestamps, and other embedded fields are identifying in their own
  right, and Obur has no use for any of it — only the risk of holding it.
- **Multiple resolutions generated per upload** (thumbnail / medium / full)
  rather than one fixed size, with the client requesting what fits its
  viewport. Avatars are cropped square; check-in photos keep their natural
  aspect ratio.
- A server-side hard cap around 15MB, as an abuse and misbehaving-client
  safety net rather than a size the normal path approaches.
- **Signed URLs for `close_friends` and `private` check-in photos only**,
  generated after `can_view` has already passed. A check-in's visibility is
  enforced on its database row, but the photo lives in R2 — reachable
  directly if the URL escapes, without passing through any authorization at
  all. Public photos and avatars are deliberately left unsigned: there is no
  boundary left to enforce once something is public, and signing would cost
  real CDN cacheability for nothing gained.
- Orphaned objects cleaned up when the associated row is deleted.
- Image processing is CPU-bound and runs via `asyncio.run_in_executor`.

**Why now:** the signed-URL decision depends on Phase 10's completed
visibility-and-blocking model, and Phase 16's feed and derived venue photo
consume real uploaded images.

## Phase 16 — Feed & Discovery

- **Two-layer main feed** (PDD §12). Layer 1 is public check-ins and lists
  from followed users, chronologically. Layer 2 is algorithmic fill, which
  engages once Layer 1 falls below a threshold of the feed — the cold-start
  answer for a new user and the keep-it-alive answer for a user who follows
  few people. **Both layers take mute and block as query inputs**, not as a
  filter applied afterward.
- Layer 2 ranking signals in PDD §12's stated priority order: check-ins
  at venues whose `VENUE_CATEGORY` this user rates highly, then
  content from the user's current city, then like count. Algorithmic items
  are flagged in the response so the client can mark them as suggested.
- **Discover search across four types** — venue, user, list, and
  **hashtag**, the last of which the original roadmap's discovery line
  didn't cover. City filter doubles as travel mode's manual city selector.
- Discover ranking: aggregate rating, then check-in count, then check-in
  count among followed users (the "3 friends have been" signal). Among equal
  ratings, recently logged content ranks higher.
- **A venue's representative photo is derived, never uploaded** — whichever
  of its own `public` check-ins currently has the most likes, computed live
  at read time rather than stored on `VENUE`, so it is always current with no
  invalidation logic to get wrong. The selection is **per-viewer**: it
  excludes anyone the viewer has blocked or is blocked by, which naturally
  surfaces the next-best-liked eligible photo for a blocked pair. Scoped to
  blocking only, not muting. The photo links through to its source check-in.
  A venue with no public check-ins simply shows none.
- "First discoverer" on a venue page, with the same per-viewer
  anonymization.

**Why now:** its ranking signals come from Phase 13, its exclusions from
Phase 10, and its imagery from Phase 15. This is the most dependency-laden
surface in the PDD, which is why it is last among the feature phases rather
than first.

## Phase 17 — Notification Preferences & PDD Coverage Audit

- **Per-trigger notification opt-out** (new follower, check-in like, list
  like, badge earned, mention) — storage plus enforcement at every write
  path that creates a notification. It sits here because every notification
  type only exists as of Phase 14.
- **Recent likes activity view** — a user's own like history across
  check-ins and lists (PDD §5's Settings → Activity).
- **A full PDD coverage audit.** Every row of §6's feature catalog, every
  table in §7, and every requirement in §17 is checked against what exists.
  Anything missing is either built here or moved to
  [Out of Scope](#out-of-scope) with a written reason — nothing is left
  silently unaddressed. The [PDD Coverage Matrix](#pdd-coverage-matrix)
  below is brought to its final state as the output.

**Why now:** this phase is the evidence for this roadmap's central claim —
that client work can start without anyone needing to come back to the
backend. That claim is worth auditing deliberately rather than assuming.

## Phase 18 — Release 1.0.0

- Full integration pass across the real surface: auth, check-in creation,
  venue search, feed, moderation.
- The 98% coverage bar and the N+1 query-count tests verified across every
  list endpoint, not just the ones that had them first.
- `CHANGELOG.md`'s `[Unreleased]` becomes `[1.0.0]`, `pyproject.toml`'s
  version matches, and the commit is tagged `v1.0.0` — by a human, per the
  shared release process.
- What 1.0.0 means here: the API contract is now stable enough for
  `obur-web` and `obur-mobile` to build against without expecting it to
  break underneath them.

**Explicitly not in scope:** load and performance testing. The MVP target is
200 MAU; at that scale there is no real traffic pattern to test against yet.
Revisit if that target changes.

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
| Governing principle / RLS | 7 + Standing Rules; infrastructure layer in 8 |
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
| RLS policies, table by table | 7 + Standing Rules |
| "You Might Like" activation volume | Out of scope — v2.0 |
| TRY pricing, second-city timing | Out of scope — not engineering work |
| Meilisearch migration threshold | Out of scope — deferred |
| Fraud detection tooling | Out of scope — deferred |
| Accessibility | Out of scope — client |
| Legal research items | Out of scope — needs a lawyer |
