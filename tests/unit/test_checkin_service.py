"""Unit tests for app.services.checkin — every DB call is mocked."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.visibility import Visibility
from app.exceptions import (
    CheckinNotFoundError,
    DuplicateProductRatingError,
    EmptyProductListError,
    FutureVisitDateError,
    NotCheckinOwnerError,
    ProductNotAtVenueError,
    VenueNotFoundError,
)
from app.models.checkin import Checkin
from app.models.checkin_product import CheckinProduct
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.services import checkin as checkin_service
from app.services.checkin import ProductRating

_TZ = "Europe/Istanbul"


def _user(user_id: object = None, role: str = UserRole.USER) -> User:
    return User(
        id=user_id or uuid4(), auth_provider="clerk", auth_provider_id="x", role=role
    )


def _checkin(**overrides: object) -> Checkin:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "user_id": uuid4(),
        "venue_id": uuid4(),
        "visibility": Visibility.PUBLIC,
        "visited_at": date.today(),
        "visited_tz": _TZ,
        "deleted_at": None,
    }
    defaults.update(overrides)
    return Checkin(**defaults)


def _session_for_create(
    *, venue: Venue | None, available_product_ids: list[object]
) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock(return_value=venue)
    result = MagicMock()
    result.scalars.return_value.all.return_value = available_product_ids
    session.execute.return_value = result
    return session


async def test_create_checkin_raises_when_venue_not_found() -> None:
    session = _session_for_create(venue=None, available_product_ids=[])

    with pytest.raises(VenueNotFoundError):
        await checkin_service.create_checkin(
            session,
            user_id=uuid4(),
            venue_id=uuid4(),
            products=[ProductRating(product_id=uuid4(), rating=4)],
            visited_at=date.today(),
            visited_tz=_TZ,
        )

    session.add.assert_not_called()


async def test_create_checkin_raises_when_no_products() -> None:
    session = _session_for_create(venue=MagicMock(spec=Venue), available_product_ids=[])

    with pytest.raises(EmptyProductListError):
        await checkin_service.create_checkin(
            session,
            user_id=uuid4(),
            venue_id=uuid4(),
            products=[],
            visited_at=date.today(),
            visited_tz=_TZ,
        )


async def test_create_checkin_raises_on_duplicate_product() -> None:
    session = _session_for_create(venue=MagicMock(spec=Venue), available_product_ids=[])
    product_id = uuid4()

    with pytest.raises(DuplicateProductRatingError):
        await checkin_service.create_checkin(
            session,
            user_id=uuid4(),
            venue_id=uuid4(),
            products=[
                ProductRating(product_id=product_id, rating=4),
                ProductRating(product_id=product_id, rating=2),
            ],
            visited_at=date.today(),
            visited_tz=_TZ,
        )


async def test_create_checkin_raises_on_future_visit_date() -> None:
    session = _session_for_create(venue=MagicMock(spec=Venue), available_product_ids=[])
    tomorrow = datetime.now(ZoneInfo(_TZ)).date() + timedelta(days=1)

    with pytest.raises(FutureVisitDateError):
        await checkin_service.create_checkin(
            session,
            user_id=uuid4(),
            venue_id=uuid4(),
            products=[ProductRating(product_id=uuid4(), rating=4)],
            visited_at=tomorrow,
            visited_tz=_TZ,
        )


async def test_create_checkin_raises_when_product_not_available_at_venue() -> None:
    session = _session_for_create(venue=MagicMock(spec=Venue), available_product_ids=[])

    with pytest.raises(ProductNotAtVenueError):
        await checkin_service.create_checkin(
            session,
            user_id=uuid4(),
            venue_id=uuid4(),
            products=[ProductRating(product_id=uuid4(), rating=4)],
            visited_at=date.today(),
            visited_tz=_TZ,
        )


async def test_create_checkin_succeeds_with_available_products() -> None:
    product_id = uuid4()
    session = _session_for_create(
        venue=MagicMock(spec=Venue), available_product_ids=[product_id]
    )

    checkin = await checkin_service.create_checkin(
        session,
        user_id=uuid4(),
        venue_id=uuid4(),
        products=[ProductRating(product_id=product_id, rating=4)],
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    assert checkin.visited_tz == _TZ
    # One add for the checkin, one for its single product.
    assert session.add.call_count == 2
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()


async def test_get_checkin_raises_when_not_found() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(session, uuid4(), viewer=None)


async def test_get_checkin_raises_when_soft_deleted() -> None:
    session = AsyncMock()
    session.get = AsyncMock(
        return_value=_checkin(
            deleted_at=datetime.now(UTC), visibility=Visibility.PUBLIC
        )
    )

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(session, uuid4(), viewer=None)


async def test_get_checkin_raises_when_private_and_no_viewer() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_checkin(visibility=Visibility.PRIVATE))

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(session, uuid4(), viewer=None)


async def test_get_checkin_raises_when_private_and_viewer_is_not_owner() -> None:
    session = AsyncMock()
    session.get = AsyncMock(
        return_value=_checkin(visibility=Visibility.PRIVATE, user_id=uuid4())
    )

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(session, uuid4(), viewer=_user())


async def test_get_checkin_returns_private_checkin_to_its_owner() -> None:
    owner = _user()
    session = AsyncMock()
    session.get = AsyncMock(
        return_value=_checkin(visibility=Visibility.PRIVATE, user_id=owner.id)
    )

    result = await checkin_service.get_checkin(session, uuid4(), viewer=owner)

    assert result.visibility == Visibility.PRIVATE


async def test_get_checkin_returns_private_checkin_to_an_admin() -> None:
    admin = _user(role=UserRole.ADMIN)
    session = AsyncMock()
    session.get = AsyncMock(
        return_value=_checkin(visibility=Visibility.PRIVATE, user_id=uuid4())
    )

    result = await checkin_service.get_checkin(session, uuid4(), viewer=admin)

    assert result.visibility == Visibility.PRIVATE


async def test_get_checkin_returns_public_checkin_to_anyone() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_checkin(visibility=Visibility.PUBLIC))

    result = await checkin_service.get_checkin(session, uuid4(), viewer=None)

    assert result.visibility == Visibility.PUBLIC


async def test_update_checkin_raises_when_not_found() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.update_checkin(
            session, uuid4(), current_user=_user(), updates={}
        )


async def test_update_checkin_raises_when_not_owner() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_checkin(user_id=uuid4()))

    with pytest.raises(NotCheckinOwnerError):
        await checkin_service.update_checkin(
            session, uuid4(), current_user=_user(), updates={"note": "x"}
        )


async def test_update_checkin_raises_on_future_visit_date() -> None:
    owner = _user()
    session = AsyncMock()
    session.get = AsyncMock(return_value=_checkin(user_id=owner.id))
    tomorrow = datetime.now(ZoneInfo(_TZ)).date() + timedelta(days=1)

    with pytest.raises(FutureVisitDateError):
        await checkin_service.update_checkin(
            session,
            uuid4(),
            current_user=owner,
            updates={"visited_at": tomorrow},
        )


async def test_update_checkin_applies_editable_fields_for_the_owner() -> None:
    owner = _user()
    checkin = _checkin(user_id=owner.id)
    session = AsyncMock()
    session.get = AsyncMock(return_value=checkin)

    result = await checkin_service.update_checkin(
        session, checkin.id, current_user=owner, updates={"note": "harika"}
    )

    assert result.note == "harika"
    session.commit.assert_awaited_once()


async def test_update_checkin_ignores_non_editable_fields() -> None:
    owner = _user()
    checkin = _checkin(user_id=owner.id)
    other_venue_id = uuid4()
    session = AsyncMock()
    session.get = AsyncMock(return_value=checkin)

    result = await checkin_service.update_checkin(
        session,
        checkin.id,
        current_user=owner,
        updates={"venue_id": other_venue_id},
    )

    assert result.venue_id != other_venue_id


async def test_soft_delete_checkin_raises_when_not_found() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.soft_delete_checkin(
            session, uuid4(), current_user=_user()
        )


async def test_soft_delete_checkin_raises_when_already_deleted() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_checkin(deleted_at=datetime.now(UTC)))

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.soft_delete_checkin(
            session, uuid4(), current_user=_user()
        )


async def test_soft_delete_checkin_raises_when_not_owner() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_checkin(user_id=uuid4()))

    with pytest.raises(NotCheckinOwnerError):
        await checkin_service.soft_delete_checkin(
            session, uuid4(), current_user=_user()
        )


async def test_soft_delete_checkin_marks_deleted_at_for_the_owner() -> None:
    owner = _user()
    checkin = _checkin(user_id=owner.id)
    session = AsyncMock()
    session.get = AsyncMock(return_value=checkin)

    await checkin_service.soft_delete_checkin(session, checkin.id, current_user=owner)

    assert checkin.deleted_at is not None
    session.commit.assert_awaited_once()


async def test_soft_delete_checkin_allows_admin_on_someone_elses_checkin() -> None:
    admin = _user(role=UserRole.ADMIN)
    checkin = _checkin(user_id=uuid4())
    session = AsyncMock()
    session.get = AsyncMock(return_value=checkin)

    await checkin_service.soft_delete_checkin(session, checkin.id, current_user=admin)

    assert checkin.deleted_at is not None


async def test_hard_delete_checkin_raises_when_not_found() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.hard_delete_checkin(session, uuid4())


async def test_hard_delete_checkin_deletes_and_commits() -> None:
    checkin = _checkin()
    session = AsyncMock()
    session.get = AsyncMock(return_value=checkin)

    await checkin_service.hard_delete_checkin(session, checkin.id)

    session.delete.assert_awaited_once_with(checkin)
    session.commit.assert_awaited_once()


async def test_get_products_for_checkins_returns_empty_dict_for_empty_input() -> None:
    session = AsyncMock()

    result = await checkin_service.get_products_for_checkins(session, [])

    assert result == {}
    session.execute.assert_not_called()


async def test_get_products_for_checkins_groups_by_checkin_id() -> None:
    checkin_id_a, checkin_id_b = uuid4(), uuid4()
    rows = [
        CheckinProduct(
            id=uuid4(), checkin_id=checkin_id_a, product_id=uuid4(), rating=4
        ),
        CheckinProduct(
            id=uuid4(), checkin_id=checkin_id_a, product_id=uuid4(), rating=3
        ),
        CheckinProduct(
            id=uuid4(), checkin_id=checkin_id_b, product_id=uuid4(), rating=2
        ),
    ]
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = rows
    session.execute.return_value = result_mock

    grouped = await checkin_service.get_products_for_checkins(
        session, [checkin_id_a, checkin_id_b]
    )

    assert len(grouped[checkin_id_a]) == 2
    assert len(grouped[checkin_id_b]) == 1


async def test_list_checkins_for_venue_returns_results() -> None:
    checkins = [_checkin(), _checkin()]
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = checkins
    session.execute.return_value = result_mock

    result = await checkin_service.list_checkins_for_venue(
        session, uuid4(), viewer=None, limit=20, offset=0
    )

    assert result == checkins


async def test_list_checkins_for_user_returns_results() -> None:
    checkins = [_checkin()]
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = checkins
    session.execute.return_value = result_mock

    result = await checkin_service.list_checkins_for_user(
        session, uuid4(), viewer=None, limit=20, offset=0
    )

    assert result == checkins
