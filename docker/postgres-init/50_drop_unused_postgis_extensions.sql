-- Obur only needs core PostGIS (geometry types + spatial queries for the
-- 50m-radius venue duplicate check in PDD section 13). The postgis/postgis
-- image also auto-installs the US Census TIGER geocoder and topology
-- extensions by default, which are irrelevant here and otherwise pollute
-- every Alembic autogenerate diff with dozens of unrelated table drops.
DROP EXTENSION IF EXISTS postgis_tiger_geocoder CASCADE;
DROP EXTENSION IF EXISTS postgis_topology CASCADE;
