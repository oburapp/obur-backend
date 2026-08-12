-- Separate database for tests/integration/ (see docs/testing-strategy.md)
-- so integration tests never touch dev data. PostGIS is installed here too
-- since it's what venue duplicate-detection queries actually exercise —
-- the point of an integration test is to run against the real thing.
CREATE DATABASE obur_test;
\connect obur_test
CREATE EXTENSION IF NOT EXISTS postgis;
