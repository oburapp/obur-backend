# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Rate limiting on every endpoint, per ADR-0014. Two tiers: a generous
  baseline for reads, and a strict one on the writes whose abuse damages
  data rather than costing bandwidth (check-in, venue, follow).
  Authenticated callers are keyed by user id, anonymous ones by an
  HMAC of their address that is never stored or logged. Fixed-window
  counters rather than a sliding log, chosen on memory-safety grounds:
  a precise limiter with attacker-chosen keys is a way to exhaust the
  store that protects us. Refusals carry `Retry-After` and the
  widely implemented `RateLimit-*` fields
- The client address is resolved rightmost-ish from `X-Forwarded-For`
  (`app/core/client_ip.py`). Reading the header from the left is a
  documented rate-limiter bypass — an attacker spoofs a fresh prefix per
  request and never fills a counter. `TRUSTED_PROXY_COUNT` is required
  configuration with no default, because a wrong value fails silently
  in both directions
- RFC 9457 problem responses on every error path, per ADR-0015.
  One body shape — including FastAPI's own validation errors, which are
  normalised into it — so a client writes one parser. `type` is the
  machine-readable discriminator, which is what finally separates the
  two conditions that both return 429: rate limiting, and a username
  changed too recently
- `X-Request-ID` on every response, on every log line, and in every
  problem body, so a person reporting a failure can name it and have it
  found. An inbound id is honoured only if it validates — an
  unvalidated client string written to every log line is a
  log-injection vector
- Structured request logging: method, route template, status, and
  duration as JSON fields. The route *template*, never the path, so
  lines aggregate and no identifier reaches the log through a URL. The
  client address is excluded deliberately — stricter than OWASP's list,
  because ADR-0014's position is that an address may be counted against
  but not recorded
- `GET /api/v1/venue-categories`: the category tree with names resolved
  for the request. Public and unauthenticated, because a client needs it
  to render the venue creation form and Discover's filters before anyone
  signs in. Deliberately unpaginated, the one exception to this repo's
  pagination rule: the catalog is curated and bounded, and half a tree is
  a broken picker rather than a shorter list. A test enforces the ceiling
  so that stays a fact rather than a promise
- `app/core/locale.py`: request-time locale resolution. A signed-in
  user's own `locale` wins, since it is an explicit settings choice that
  should follow them onto a borrowed device; `Accept-Language` is the
  fallback for anonymous callers, and `DEFAULT_LOCALE` when neither names
  something supported
- English locale seeds, and `SUPPORTED_LOCALES` goes from `("tr",)` to
  `("tr", "en")` — PDD §6 lists both as MVP, and a language the seeds
  don't cover isn't really supported
- `VenueResponse.category_name`, resolved per request beside the raw
  `category_id`. One catalog lookup per request regardless of how many
  venues come back
- Two-role database architecture and Row Level Security on every table,
  per ADR-0016. The API now connects as a least-privilege `obur_app`
  role instead of the table owner, which PostgreSQL exempts from its
  own policies, so a policy re-expressing `can_view` in SQL is a real
  second layer, one that survives a query that forgot to call it, not
  just the same rule written twice
- Production deployment on Railway: backend, PostgreSQL+PostGIS, and
  Redis all live in EU West, per `docs/deployment.md`. Migrations run
  via a Pre-deploy Command before a new version takes traffic, so a
  broken migration stops the deploy instead of reaching production
- The Clerk webhook is registered against the live deployed URL, open
  since Phase 1 for want of a public URL. `user.created`/`updated`/
  `deleted` now actually sync, not just build and pass unit tests
- GitHub Actions CI (lint, typecheck, the full test suite against a
  real Postgres and Redis, a Docker build) required to pass before
  merging to `main`, and before Railway deploys it
- `VENUE.district`, required on every newly created venue, per ADR-0009.
  Unblocks district-scoped badges and ranking later; existing venues
  stay `NULL`, no backfill
- Two-layer venue duplicate detection: an exact `google_places_id`
  match resolves to the existing venue idempotently and isn't
  bypassable via `confirm_duplicate`, a certain duplicate needs no
  confirmation prompt. The existing 50-metre radius check is now the
  fallback for everything without a Google identity to match on
- `VENUE.is_verified`, cosmetic only, never affects ranking or search.
  Auto-sets once a venue with a `google_places_id` has 3 independent
  public check-ins; without one, 5 independent check-ins make a venue
  eligible for an admin to confirm via the new
  `POST /admin/venues/{id}/verify`, but check-ins alone never verify it
- Dependency vulnerability scanning: a `uv audit` job in CI, plus
  Dependabot covering both Python and GitHub Actions dependencies


### Changed

- Routes no longer catch their own domain exceptions to convert them
  into HTTP errors. Thirty-three `try`/`except` blocks came out; the
  exceptions now reach handlers registered per domain base class. Around
  fifteen call sites had been returning `detail=str(e)`, sending
  internal exception text to callers — `NotListOwnerError` reached a
  client as `"user 8f3a… may not delete list 2b1c…"`. Exception messages
  are developer-facing text and stay in the logs
- Adding a venue that is already in a list returns `409`, not `422`.
  It is a state conflict, not a malformed request, and `422` is what
  schema validation already means here
- The venue category catalog grows from 9 entries to 48 (4 roots, 44
  leaves) and is restructured to classify venue **format** only, per
  ADR-0013. `VENUE.category_id` became the platform's only classification
  dimension when the product layer was removed (ADR-0011), and three
  readers depend on its granularity: Discover's filters, the feed's
  taste-overlap signal, and a user's own "best per category" history.
  Roots are universal so a second market is additive; leaves are the
  Turkish seed. `parent_id` already existed, so no schema change
- The translation tables are read for the first time. They have been
  seeded since Phase 2 and no service had ever queried one, so the
  "translation tables over embedded strings" design existed only on
  paper. Resolution falls back to `DEFAULT_LOCALE` per name, so a
  partially translated catalog degrades to readable instead of blank
- `VenueResponse.status` (a single string) is replaced by two
  independent booleans, `is_active` and `is_suspended`, per ADR-0009.
  "The business closed" and "an admin suspended this listing" aren't
  the same fact, and a closed venue stays visible (shown transparently)
  while a suspended one is hidden entirely, RLS included, so collapsing
  both into one field would have hidden that difference. No venue field
  is user-editable, including by whoever added it; every correction now
  goes through the existing report-and-admin-review path

### Fixed

- The strict rate-limit tier never applied. The tier was read from
  `scope["route"]`, which Starlette does not populate until the router
  runs — after all middleware. Check-in, venue, and follow creation were
  therefore metered at the baseline 600/hour instead of 30, and failed
  *open* rather than closed when the counter store was unavailable.
  Routes are now matched against templates the limiter declares itself,
  pinned to live routes by a test so a renamed endpoint fails loudly
  instead of silently dropping a tier
- Alembic's logging setup disabled every logger that already existed,
  which is harmless when it runs as its own process and not harmless at
  all in-process: after the test suite migrated, nothing in `app/`
  logged anything again. `disable_existing_loggers=False` in
  `migrations/env.py`

### Security

- RLS on `checkin_likes`, `list_likes`, `checkin_bookmarks`, and
  `list_bookmarks` now also checks that the inserter can see the checkin
  or list they're attaching the row to, not only that they are who they
  claim to be. The application layer already enforced this, so no
  legitimate flow changes; this closes the same gap at the database
  layer that RLS exists to close everywhere else, rather than leaving it
  resting on the ORM's insert path issuing `RETURNING`

## [0.6.0] - 2026-08-24

### Added

- `CHECKIN.rating_taste`, making four required venue criteria — taste,
  service, ambiance, value. Food quality previously lived entirely in
  `CHECKIN_PRODUCT.rating`, so removing the product layer without this
  would have left a food-and-drink platform that rates atmosphere and
  service but never the food (ADR-0011)
- `USER.display_name` (free text, deliberately not unique) and
  `USER.status` (`active`/`frozen`/`suspended`, kept separate from
  `role` — one is standing, the other permission); `username` becomes a
  required unique handle
- `app/core/user_identity.py`: the defaults both user-creating paths
  derive from. Clerk's `username` is optional and the JIT fallback has
  no profile data at all, so a required handle needs generating — done
  deterministically from the provider identity pair, so the webhook and
  the JIT path can race and still produce the same handle
- `app/seeds/runner.py` and `just seed` / `just setup-db`: an idempotent
  reference-data seeder, replacing the seed migration (ADR-0012)
- Self-service account management: `PATCH /api/v1/users/me`,
  `POST /api/v1/users/me/freeze`, and `DELETE /api/v1/users/me`. Freezing
  is reversed by simply signing back in — there is no unfreeze endpoint to
  find — while suspension stays admin-only and is never user-reversible
- `USER.username_changed_at`, backing a rate limit on handle changes. An
  unrestricted handle is an impersonation vector in a way a display name
  isn't; the window lives on the row rather than in Redis, since a cache
  flush must not hand someone a fresh allowance
- Frozen and suspended accounts drop out of other people's listings via a
  shared query predicate (`app.core.authz.account_is_visible`), applied as
  a condition rather than a post-filter so page sizes stay honest
- `README.md`
- `tests/unit/test_migration_isolation.py`: fails if any file under
  `migrations/versions/` imports from `app/`

### Removed

- The product layer — `PRODUCT`, `GLOBAL_PRODUCT_TYPE` (+ its
  translation table), and `CHECKIN_PRODUCT`, with their services,
  schemas, endpoints, seed data, and tests. At MVP volume no individual
  item could reach §8's 10-rating floor, so the two check-in steps this
  cost every user returned no label; what was eaten belongs in `note`.
  See ADR-0011 in obur-docs
- `POST/GET /api/v1/products`, and the product list on check-in
  creation — a check-in is now a venue and four ratings

### Fixed

- The Clerk `user.deleted` webhook could not delete any user who had
  ever created content. It issued a plain `DELETE` against `users`, and
  no foreign key referencing `users.id` declared an `ondelete` — so the
  delete failed on a foreign-key violation, the webhook returned 500,
  Clerk retried indefinitely, and the account stayed in our database
  after being deleted at the provider. Written in Phase 1 when nothing
  referenced `users.id` yet, with a comment to revisit once check-ins
  and follows existed; they have since Phase 3. All twelve references
  now declare a policy: eleven `CASCADE` (personal content is purged
  with the account), and `VENUE.added_by` `SET NULL`, since a venue is a
  shared resource that outlives whoever added it

### Changed

- `app/services/list.py` split into the list itself and
  `app/services/list_item.py` for its contents — both were over the
  300-line limit this repo sets for itself, and ordering is a separate
  concern from the list it orders
- `rating_value` redefined from "the payoff of the overall experience" to
  **value for money** (Turkish label *Değer* → *Fiyat*). With taste,
  service, and ambiance each rated separately, the old definition
  overlapped all three and measured nothing of its own; as a price
  signal it is the only criterion that can tell an excellent venue from
  an excellent venue that overcharges
- `docs/roadmap.md` rewritten from Phase 5 onward to cover the PDD in
  full. The old version was written against an earlier PDD and had
  drifted both ways: shipped code contradicting the PDD in about a dozen
  places, and about a dozen PDD domains no phase covered at all. Phases
  0–4 are kept verbatim as the record of what actually shipped. Three new
  sections make the coverage claim checkable — **Standing Rules** (a
  per-phase definition of done, including PDD/ER/ADR updated in the same
  PR as the decision that changed them), **Out of Scope**, and a **PDD
  Coverage Matrix**. Cross-cutting concerns move to Phase 7 and are
  applied by every phase after it, rather than deferred to one late phase
  the way the drift being corrected here originally happened
- `docs/roadmap.md` and `docs/project-structure.md` updated for ADR-0011.
  Phase 13 shrinks — the two-level aggregate collapses to a single
  venue-level score, the cross-venue item ranking is gone, and
  personalized history is re-keyed from `GLOBAL_PRODUCT_TYPE` to
  `VENUE.category_id`. Phase 6 picks up expanding the venue-category
  catalog from its current 9 entries, since `VENUE.category_id` is now
  the platform's only classification dimension and three separate
  readers depend on its granularity
- Catalog seeding moved out of migration `61f7b67600da` into
  `app/seeds/runner.py`, an idempotent upsert run explicitly rather than
  as a migration step — `just seed`, `just setup-db`, and the integration
  session fixture. The migration is now a documented no-op, keeping its
  revision so the chain stays intact. Its five `app/` imports were what
  broke Alembic entirely when ADR-0011 removed a seed module, and
  reference data was in the wrong place regardless: Phase 6 grows the
  venue-category catalog, and a one-shot migration had no way to apply
  that growth. See ADR-0012 in obur-docs
- `docs/project-structure.md` resynced with the actual filesystem
  (`docker/`, `justfile`, `alembic.ini`, and most of `app/core/` were
  missing) and every entry that doesn't exist yet is now annotated with
  the phase that adds it, so the file reads as a plan being tracked
  rather than an aspiration

## [0.5.0] - 2026-08-19

### Added

- `FOLLOW` and `CLOSE_FRIEND` models — one-directional, no-approval
  following, plus a manually curated close-friends list (a subset of a
  user's own followers) that grants access to `close_friends`-visibility
  content. A close friend can never outlive the follow it depended on:
  the composite foreign key to `FOLLOW` cascades the removal
  automatically on unfollow
- Shared three-tier `visibility` (`public`/`close_friends`/`private`)
  replacing `CHECKIN.is_public`, extended identically to the new `LIST`
  and `VENUE_SAVE` models — one authorization function
  (`app.core.authz.can_view`) for all three
- `LIST`/`LIST_ITEM` models and full CRUD, including item add/move/remove
  with fractional-indexing ordering (`fractional-indexing` package) — an
  insert, move, or removal writes only the one row being changed
- `CHECKIN_LIKE`/`LIST_LIKE` and `CHECKIN_BOOKMARK`/`LIST_BOOKMARK`
  models — likes are a visible signal, bookmarks are always private with
  no exposed count; both require the actor to already be able to see the
  target
- `NOTIFICATION` model, created synchronously in the same transaction as
  the triggering action (new follower, check-in like, list like) — no
  queue or background worker; `read_at` lives on the backend row for
  automatic cross-device consistency
- Endpoints for all of the above: follow/unfollow/followers/following,
  close-friends add/remove/list, list CRUD + items + like + bookmark,
  check-in like + bookmark, venue-save CRUD, and notification
  list/unread-count/mark-all-read
- `app.core.authz.ensure_visible_and_owned`: a shared guard for every
  owner-gated mutation (`CHECKIN`, `LIST`, `VENUE_SAVE` update/delete)
  that checks visibility before ownership, so a non-owner who can't even
  see a resource gets the same 404 a nonexistent id would — never a 403
  that would leak the id's existence

### Fixed

- A stranger `PATCH`ing or `DELETE`ing a private check-in, list, or
  venue save they don't own got a 403 (confirming the resource exists)
  instead of the 404 a nonexistent id would get, contradicting this
  codebase's own stated design goal that a hidden resource must be
  indistinguishable from a nonexistent one. Found via adversarial
  testing, not a bug report; fixed uniformly across all three resource
  types via `ensure_visible_and_owned` (see Added above)
- Listing a user's bookmarked check-ins/lists returned entries whose
  target had since been made private (or soft-deleted) by its owner,
  even though the bookmarker could no longer actually view them —
  bookmark listings now re-check visibility at read time, not just at
  bookmark time
- `venue_saves.type` had no database-level constraint on its allowed
  values, unlike `visibility` on the same table — added a `CHECK`
  constraint matching the existing pattern
- `pyproject.toml`'s coverage config was missing
  `concurrency = ["greenlet"]`; without it, coverage.py silently
  undercounted exception branches inside integration tests, since
  SQLAlchemy's async engine bridges sync DBAPI calls into the event loop
  via `greenlet_spawn`

## [0.4.0] - 2026-08-18

### Added

- `CHECKIN`, `CHECKIN_PRODUCT` models — a visit and its rated products,
  created together in one transaction. A product can't be rated twice
  in the same check-in; deleting a check-in is a soft delete, so a
  badge or aggregate rating already computed from it can't be
  retroactively corrupted
- `USER.role` (`user` | `admin`) and an ownership/admin authorization
  layer (`app/core/authz.py`): a user may act on their own check-ins,
  an admin on anyone's. Never settable through any endpoint — the first
  admin account is set directly in the database, by hand
- `POST/GET/PATCH/DELETE /api/v1/checkins/{id}`,
  `GET /api/v1/venues/{id}/checkins`, `GET /api/v1/users/{id}/checkins`
  — a private check-in is invisible to anyone but its owner or an
  admin, indistinguishable from a nonexistent one
- `DELETE /api/v1/admin/checkins/{id}` — admin-only permanent deletion,
  a separate endpoint from the regular (always-soft) delete so a
  destructive, irreversible action can't be triggered by accident

### Fixed

- Several foreign key columns had no index despite being filtered in
  real queries (`venues.added_by`/`category_id`,
  `products.venue_id`/`global_type_id`, `venue_categories.parent_id`,
  `global_product_types.category_id`,
  `venue_saves.user_id`/`venue_id`)

## [0.3.0] - 2026-08-13

### Added

- `VENUE`, `PRODUCT`, `VENUE_CATEGORY`, `GLOBAL_PRODUCT_TYPE`, and
  `VENUE_SAVE` models, with hierarchical categories and a
  translation-table pattern for multi-language display names
- Seed data for the initial venue category and product type catalog
  (Turkish), with one file per locale so adding a new language needs no
  code changes elsewhere
- Duplicate-venue detection: a new venue within 50 meters of an existing
  one is flagged before insert, so the client can prompt "did you mean
  this one?" instead of creating a near-duplicate
- Venue name search using PostgreSQL trigram similarity, tolerant of
  typos, partial input, and names typed without Turkish diacritics —
  chosen over language-specific full-text search to work uniformly
  across languages as the platform expands beyond Turkish
- `POST/GET /api/v1/venues`, `GET /api/v1/venues/{id}`
- `POST/GET /api/v1/products`, `GET /api/v1/products/{id}`

## [0.2.0] - 2026-08-13

### Added

- `USER` model, with provider-agnostic `auth_provider` / `auth_provider_id`
  identity fields, and its initial migration
- Clerk session token verification (`app/core/security.py`)
- `get_current_user` auth dependency, with JIT user provisioning as a
  fallback
- Clerk webhook endpoint (`user.created` / `.updated` / `.deleted`) with
  Svix signature verification, keeping `User` rows in sync
- `GET /api/v1/users/me`
- `just` task runner for common dev commands (lint, format, typecheck,
  test, local infra, migrations)

## [0.1.0] - 2026-08-13

### Added

- Development guide (`CLAUDE.md`)
- Project structure reference (`docs/project-structure.md`)
- Environment variable reference (`.env.example`)
- FastAPI application skeleton with a `/health` endpoint that verifies real
  PostgreSQL and Redis connectivity
- Async SQLAlchemy engine and session management for PostgreSQL + PostGIS
- Redis client and connectivity check
- Docker Compose local development environment (PostgreSQL+PostGIS, Redis)
  with configurable host ports to avoid local port collisions
- Alembic migrations, wired to the application's models and settings
- Unit and integration test suite (98% coverage enforced), with a
  dedicated `obur_test` database kept in sync via automatic migrations
- Testing strategy documentation (`docs/testing-strategy.md`)
- Configuration standards documenting the production-vs-local-only rule
  for environment values

### Changed

- Formatter switched from Black to `ruff format`
