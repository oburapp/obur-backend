"""Shared geospatial constants.

Used by both the `Venue.location` generated column (app/models/venue.py)
and any service-side query that builds a point or distance filter (e.g.
`app.services.venue`) — kept in one place so they can never drift apart.
"""

# WGS 84 — standard SRID for raw GPS lat/lng coordinates.
WGS84_SRID = 4326
