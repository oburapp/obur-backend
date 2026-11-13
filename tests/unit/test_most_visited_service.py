"""Unit tests for app.services.most_visited's application-side checks.

In the database RLS already hides a blocked pair from each other, so the
service's own block check is only reachable here, with RLS out of the
picture: it proves the application doesn't rely on RLS alone.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

from pytest_mock import MockerFixture

from app.core.visibility import Visibility
from app.models.user import User
from app.services import most_visited


async def test_a_blocked_viewer_gets_an_empty_list_even_without_rls(
    mocker: MockerFixture,
) -> None:
    owner = User(id=uuid4(), most_visited_visibility=Visibility.PUBLIC)
    viewer = User(id=uuid4(), role="user")
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=owner)
    mocker.patch(
        "app.services.most_visited.is_blocked_between", AsyncMock(return_value=True)
    )

    places = await most_visited.list_most_visited(session, owner.id, viewer=viewer)

    assert places == []
    session.execute.assert_not_awaited()
