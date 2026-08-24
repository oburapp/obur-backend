"""Middleware registered against the app, running on every request.

Distinct from `app/core/`, which is imported and called explicitly by
application code: nothing here has a caller inside the request handlers.
"""
