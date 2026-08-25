# Deployment

> **Status: live.** The Railway project described below is deployed and
> running (`obur-backend`, `postgis`, `Redis`, EU West). Most of this
> document is now a verified account of the real system, not a plan.
> The two items still open are named in
> [Still open](#still-open) below, not silently assumed done.

Platform: [Railway](https://railway.com). Backend service, PostgreSQL,
and Redis, all in the same region, per `docs/roadmap.md` Phase 8.

## Why Railway, not a fully free stack

Revisited and confirmed during Phase 8 planning, since the team is
budget-conscious and Railway's Hobby plan has a real, if small, monthly
cost ($5). A fully free stack was researched as the alternative: Google
Cloud Run for compute (a genuine, uncapped free tier, but most of its
free quota is US-region-only, which would make the distance-to-Turkey
problem worse, not better), Neon for Postgres (a genuine free tier with
PostGIS support, but only 0.5 GB storage, tight enough to need active
watching), and a separate provider like Upstash for Redis. Render's free
tier was also checked and ruled out outright: its web services sleep
after 15 minutes of inactivity with a 30-60 second cold start on the next
request, and its free Postgres expires 30 days after creation.

Stitching three separate free-tier vendors together would recreate, per
vendor, what Railway already provides as one platform: the Pre-deploy
Command mechanism migrations rely on, the Cron Job mechanism backups rely
on, and a Postgres image with PostGIS ready to go. Kept Railway; the $5/
month is an accepted, small cost against that operational complexity.

## Region

**EU West** (`europe-west4-drams3a`, Amsterdam). Railway currently offers
four regions total (US West, US East, EU West, Southeast Asia); EU West
is the only one that isn't a different continent from the Turkey/Istanbul
launch market, so it's the choice by elimination rather than a close
call. Actual latency from Turkey-based users should be measured once
deployed, not assumed from geographic distance alone.

## Compute: 1 replica, 1 worker

Starting point, not a permanent ceiling. Railway bills per-replica by
actual resource consumption rather than a flat fee, so a second replica
or worker is a real recurring cost, not a free availability upgrade. The
team is bootstrapped, and there are no real users yet (PDD MVP target is
200 MAU), so the availability benefit of running more than one instance
doesn't currently justify the cost. Revisit after launch based on real
observed performance and cost data, not a pre-launch guess.

## Database roles and Row Level Security

Two roles (an owner role for migrations/the seeder, and an application
role the API connects as) and RLS policies on every table, from Phase 8
onward. Full decision, rationale, and the testing bar it has to meet:
[ADR-0016](https://github.com/oburapp/obur-docs/blob/main/adr/0016-database-roles-and-row-level-security.md)
in obur-docs.

## Migrations run before the new version takes traffic

Railway's **Pre-deploy Command** runs `alembic upgrade head` in an
isolated step between build and deploy, before the new app version is
health-checked and made active. If it fails, the deploy stops there and
the new version never starts serving traffic, the old version keeps
running instead.

Every migration must stay backward-compatible with the *previous* app
version's code (add the new column/table first, remove the old one in a
later migration), because even at 1 replica Railway briefly overlaps the
old and new container during a deploy for zero-downtime cutover
(`RAILWAY_DEPLOYMENT_OVERLAP_SECONDS`), so the old code can still be
running for a few seconds against the already-migrated schema.

## Backups

Daily Railway Cron Job running `pg_dump`, uploaded to Cloudflare R2
(already a dependency for Phase 15 photo storage, not a new vendor). Full
decision and rationale, including why this was chosen over Railway's paid
Point-in-Time Recovery:
[ADR-0017](https://github.com/oburapp/obur-docs/blob/main/adr/0017-database-backup-strategy.md)
in obur-docs.

## Environment variables

See `.env.example` for the full list and
[obur-docs/CLAUDE.md](https://github.com/oburapp/obur-docs/blob/main/CLAUDE.md#environment-variables)
for the production-vs-local-only rule. What changes at this phase
specifically:

- `CLERK_WEBHOOK_SECRET`: from the empty-string sentinel to required,
  once the webhook is registered against the real deployed URL in the
  Clerk Dashboard (open since Phase 1 for want of a public URL).
- `authorized_parties` (the `azp` claim, `app/core/security.py`): set to
  the real `obur-web` / `obur-mobile` origins once they exist, closing
  the token-replay gap that's open while it's unset.
- `TRUSTED_PROXY_COUNT`: Railway does not officially document its edge
  proxy's exact hop count, and community reports on this disagree. Must
  be confirmed empirically, by logging the raw `X-Forwarded-For` header
  on a real deployed request, not assumed from this doc or from a forum
  answer.
- `APP_DATABASE_URL` and `APP_DB_ROLE_PASSWORD`: new, required, once the
  role split in ADR-0016 lands. `DATABASE_URL` keeps its existing meaning
  (the owner role, migrations and the seeder); `APP_DATABASE_URL` is the
  new least-privilege `obur_app` role the running API actually connects
  as. `APP_DB_ROLE_PASSWORD` is read directly by the migration that
  creates the role and must be kept in sync with the credentials embedded
  in `APP_DATABASE_URL`, the same relationship `POSTGRES_PASSWORD` and
  `DATABASE_URL` already have locally.
- `R2_*`: from empty-string sentinels to required, once Phase 15 photo
  storage and the ADR-0017 backup script both start consuming them.

## Health checks

Point Railway's healthcheck at the existing `/health` endpoint
(`app/main.py`), which already verifies real PostgreSQL and Redis
connectivity rather than just process liveness, no new work needed here.

## Encryption at rest and network isolation (PDD §18)

Closes PDD §18's open research item. Verified against the real
provisioned service, not just general documentation:

- **Network isolation.** `railway domain list` and `railway tcp-proxy
  list` against both `postgis` and `Redis` confirm neither has a public
  domain or TCP proxy, only `obur-backend` is publicly reachable. (A
  Railway CLI quirk to note for next time: running `railway domain
  --service <name>` with no subcommand *creates* a domain rather than
  checking for one; `railway domain list` is the read-only form. This
  was found the hard way, by briefly creating and then deleting two
  domains that should never have existed.)
- **Encryption at rest.** Confirmed directly by a Railway employee
  (ray-chen, Railway Central Station, 2024-06-18): data is encrypted "at
  the storage level," beneath the volume, so this is satisfied
  regardless of which specific database is provisioned. Railway also
  holds a SOC 2 Type II certification as of 2026, with audit reports
  available through their Trust Center on request.

**Not yet automated.** This is a manual, one-time check against the CLI.
When a CI/CD pipeline exists for this repo (none does yet, no
`.github/workflows`), network isolation at minimum should become an
automated step in it (list domains/proxies for the database services,
fail the pipeline if either is non-empty) rather than staying a thing
someone has to remember to re-check by hand.

## Still open

Genuinely unresolved, not a guess dressed up as one:

- `TRUSTED_PROXY_COUNT`'s real value: needs logging the raw
  `X-Forwarded-For` header on an actual deployed request and reading
  off the real hop count, not assuming one.
- Actual observed latency from EU West to Turkey-based users: needs
  real traffic, which doesn't exist yet (no client is deployed).
- `authorized_parties` (the `azp` claim): needs `obur-web` /
  `obur-mobile`'s real origins, which don't exist yet either.
