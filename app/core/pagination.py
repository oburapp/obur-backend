"""Shared pagination defaults for list endpoints.

Every list endpoint must be bounded (see CLAUDE.md's API Design rules) —
this is the one place that bound is defined, so every endpoint uses the
same default page size and the same ceiling instead of each picking its
own number.
"""

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
