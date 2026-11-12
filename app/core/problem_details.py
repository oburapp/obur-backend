"""RFC 9457 Problem Details: the `Problem` type and the `ProblemError`
exception that carries one. The catalog of problem types the API returns
lives in app.core.problems; this module is only the machinery. See
ADR-0015 in obur-docs.
"""

from typing import Any

from fastapi.responses import JSONResponse

CONTENT_TYPE = "application/problem+json"

_URN_PREFIX = "urn:obur:problem:"


class Problem:
    """A problem type: its URN, its human-readable title, and its status.

    Instances are module-level constants in app.core.problems, so a type is
    declared once and referenced everywhere rather than spelled out at each raise site.
    """

    def __init__(
        self, slug: str, title: str, status_code: int, detail: str = ""
    ) -> None:
        self.type = f"{_URN_PREFIX}{slug}"
        self.title = title
        self.status = status_code
        # The sentence shown when nothing more specific is known. Written
        # once here rather than repeated at every raise site, which is what
        # kept exception text leaking into responses before.
        self.detail = detail or title

    def response(
        self,
        *,
        detail: str,
        request_id: str | None = None,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> JSONResponse:
        """Render this problem as a response body.

        Extension members are permitted by the RFC and clients are required
        to ignore ones they don't recognise, so adding a field here is
        always backward compatible.
        """
        body: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "detail": detail,
        }
        if request_id is not None:
            body["request_id"] = request_id
        body.update(extensions)

        return JSONResponse(
            status_code=self.status,
            content=body,
            media_type=CONTENT_TYPE,
            headers=headers,
        )


class ProblemError(Exception):
    """Raised by a route to return a problem response.

    Carries the problem type and, where one occurrence differs from the
    next, its own detail. Omitting `detail` uses the problem's own written
    text, which is the common case, so requiring it would make every raise
    site repeat the constant it just named.

    The handler in app/main.py turns this into a response and attaches the
    request id, so no route needs to know how correlation works.
    """

    def __init__(
        self,
        problem: Problem,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        self.problem = problem
        self.detail = detail if detail is not None else problem.detail
        self.headers = headers
        self.extensions = extensions
        super().__init__(f"{problem.type}: {self.detail}")
