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

- `VENUE_CATEGORY` (+ translation), `GLOBAL_PRODUCT_TYPE` (+ translation), `VENUE`, `PRODUCT`, `VENUE_SAVE` models
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
- Create-checkin service: one `CHECKIN` + N `CHECKIN_PRODUCT` rows in a
  single transaction. Rejects an empty product list, a duplicate product
  in the same submission, a product no longer available at the venue,
  and a `visited_at` in the future relative to the visitor's own
  timezone (`visited_tz`) — not the server's, since a visitor east of
  UTC logging a visit in their early morning hours must not be rejected
  just because the server's UTC date hasn't rolled over yet.
- `is_public` is the only visibility control (no separate "contribute to
  statistics" toggle — see the PDD's Step 5, and obur-docs for why that
  toggle was dropped): it gates both feed visibility and aggregate
  rating inclusion.
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

**Why now:** depends on both USER (Phase 1) and CHECKIN (Phase 3) existing; feeds in Phase 6 depend on FOLLOW.

## Phase 5 — Badges & Aggregate Scoring

- Aggregate rating labels per PDD §8 thresholds (venue/product pages)
- `BADGE`, `BADGE_TRANSLATION`, `USER_BADGE` models
- Badge award evaluation + periodic `rarity_pct` recalculation

**Why now:** both are read-derived from CHECKIN data — needs Phase 3 populated to be testable with real-shaped data.

## Phase 6 — Feed & Discovery

- Main feed: followed-users layer + algorithmic fill layer (PDD §12)
- Discover search: venue / product / user / list, ranking signals

**Why now:** the feed algorithm's signals (ratings, likes, follows) only make sense once Phases 3–5 exist.

## Phase 7 — Storage, Rate Limiting & Ops Polish

- R2 photo upload for check-ins, signed URLs
- Redis-based rate limiting on public endpoints
- Pagination audit across all list endpoints
- `GZipMiddleware`, graceful shutdown (dispose engine, close HTTP clients)

**Why now:** these are cross-cutting concerns best retrofitted once the real endpoint surface exists, rather than guessed at upfront.

## Phase 8 — Testing & Deployment Readiness

- Unit tests to the 98% coverage bar per service
- Integration tests: auth, check-in creation, venue search
- `docs/deployment.md` written against the real Railway setup
- Register the real Clerk webhook against the deployed URL; move
  `CLERK_WEBHOOK_SECRET` from empty to required (see Phase 1)
- Set `authorized_parties` in `app/core/security.py` to the real deployed
  `obur-web` / `obur-mobile` origins (see Phase 1)
- First tagged release, `CHANGELOG.md` moves `[Unreleased]` → `[0.1.0]`

**Why last:** deployment docs and coverage targets are only meaningful once there's a real, working surface to document and test.

**Explicitly not in scope here:** load/performance testing. The PDD's MVP
target is 200 MAU — at that scale, formal load testing is premature
optimization; there's no real traffic pattern to test against yet. Revisit
if that target changes.
