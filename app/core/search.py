"""Shared venue name search configuration.

Venue name search uses `pg_trgm` trigram similarity, not PostgreSQL's
linguistic full-text search — see ADR-0003 in obur-docs. Trigram
similarity is language-agnostic and typo-tolerant, unlike a
language-specific `tsvector` config, which matters given venue names
appear in many languages and Obur's global-expansion plans.
"""

# Minimum `word_similarity()` score (0-1) for a venue name to count as a
# search match, applied via `SET LOCAL pg_trgm.word_similarity_threshold`
# per query (see app.services.venue.search_venues) rather than left at
# PostgreSQL's own session-default GUC value. Calibrated empirically
# against real venue names: common one- or two-character typos score
# 0.4-0.6, unrelated words score 0.0 — 0.3 catches the former with a
# safety margin above the latter.
MIN_NAME_SIMILARITY = 0.3
