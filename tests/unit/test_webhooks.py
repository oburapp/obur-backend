"""Tests for the Clerk webhook endpoint."""

from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture
from svix.webhooks import WebhookVerificationError

from app.api.v1.webhooks import _delete_user, _upsert_user
from app.schemas.webhook import ClerkEmailAddress, ClerkUserData

_HEADERS = {
    "svix-id": "msg_test",
    "svix-timestamp": "1700000000",
    "svix-signature": "v1,fake",
}


async def test_upsert_user_executes_an_insert_and_commits_when_new(
    mocker: MockerFixture,
) -> None:
    data = ClerkUserData(
        id="user_abc",
        username="erenm",
        email_addresses=[ClerkEmailAddress(id="idn_1", email_address="e@example.com")],
        primary_email_address_id="idn_1",
        image_url="https://img.clerk.com/x",
    )
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    identity_mock = mocker.patch(
        "app.api.v1.webhooks.set_current_user_identity", AsyncMock()
    )

    await _upsert_user(session, data)

    # No existing row: nothing to state an identity for, and none is
    # needed, the INSERT policy only requires being authenticated at all.
    identity_mock.assert_not_awaited()
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_upsert_user_sets_identity_before_updating_an_existing_user(
    mocker: MockerFixture,
) -> None:
    data = ClerkUserData(
        id="user_abc",
        username="erenm",
        email_addresses=[ClerkEmailAddress(id="idn_1", email_address="e@example.com")],
        primary_email_address_id="idn_1",
        image_url="https://img.clerk.com/x",
    )
    existing_id = uuid4()
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=existing_id)
    identity_mock = mocker.patch(
        "app.api.v1.webhooks.set_current_user_identity", AsyncMock()
    )

    await _upsert_user(session, data)

    # RLS's UPDATE policy on `users` needs identity to match the row
    # being touched, and a webhook connection never runs get_current_user,
    # so nothing else would set it (see the migration's own docstring).
    identity_mock.assert_awaited_once_with(session, existing_id)
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_delete_user_sets_identity_then_deletes_and_commits(
    mocker: MockerFixture,
) -> None:
    target_id = uuid4()
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=target_id)
    identity_mock = mocker.patch(
        "app.api.v1.webhooks.set_current_user_identity", AsyncMock()
    )

    await _delete_user(session, "user_abc")

    identity_mock.assert_awaited_once_with(session, target_id)
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_delete_user_is_a_noop_when_never_found(
    mocker: MockerFixture,
) -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    identity_mock = mocker.patch(
        "app.api.v1.webhooks.set_current_user_identity", AsyncMock()
    )

    await _delete_user(session, "user_abc")

    identity_mock.assert_not_awaited()
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_webhook_returns_401_when_webhook_secret_is_not_configured(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch("app.api.v1.webhooks.settings.clerk_webhook_secret", "")

    response = await client.post(
        "/api/v1/webhooks/clerk", content=b"{}", headers=_HEADERS
    )

    assert response.status_code == 401


async def test_webhook_returns_401_on_invalid_signature(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.webhooks.Webhook.verify",
        side_effect=WebhookVerificationError("bad signature"),
    )

    response = await client.post(
        "/api/v1/webhooks/clerk", content=b"{}", headers=_HEADERS
    )

    assert response.status_code == 401


async def test_webhook_upserts_user_on_user_created(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    payload = {
        "type": "user.created",
        "data": {
            "id": "user_abc",
            "username": "erenm",
            "email_addresses": [{"id": "idn_1", "email_address": "e@example.com"}],
            "primary_email_address_id": "idn_1",
            "image_url": "https://img.clerk.com/x",
        },
    }
    mocker.patch("app.api.v1.webhooks.Webhook.verify", return_value=payload)
    upsert_mock = mocker.patch("app.api.v1.webhooks._upsert_user", AsyncMock())

    response = await client.post(
        "/api/v1/webhooks/clerk", content=b"{}", headers=_HEADERS
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    upsert_mock.assert_awaited_once()


async def test_webhook_upserts_user_on_user_updated(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    payload = {"type": "user.updated", "data": {"id": "user_abc"}}
    mocker.patch("app.api.v1.webhooks.Webhook.verify", return_value=payload)
    upsert_mock = mocker.patch("app.api.v1.webhooks._upsert_user", AsyncMock())

    response = await client.post(
        "/api/v1/webhooks/clerk", content=b"{}", headers=_HEADERS
    )

    assert response.status_code == 200
    upsert_mock.assert_awaited_once()


async def test_webhook_deletes_user_on_user_deleted(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    payload = {"type": "user.deleted", "data": {"id": "user_abc"}}
    mocker.patch("app.api.v1.webhooks.Webhook.verify", return_value=payload)
    delete_mock = mocker.patch("app.api.v1.webhooks._delete_user", AsyncMock())

    response = await client.post(
        "/api/v1/webhooks/clerk", content=b"{}", headers=_HEADERS
    )

    assert response.status_code == 200
    delete_mock.assert_awaited_once()


async def test_webhook_ignores_unrecognized_event_type(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    payload = {"type": "session.created", "data": {"id": "sess_abc"}}
    mocker.patch("app.api.v1.webhooks.Webhook.verify", return_value=payload)
    upsert_mock = mocker.patch("app.api.v1.webhooks._upsert_user", AsyncMock())
    delete_mock = mocker.patch("app.api.v1.webhooks._delete_user", AsyncMock())

    response = await client.post(
        "/api/v1/webhooks/clerk", content=b"{}", headers=_HEADERS
    )

    assert response.status_code == 200
    upsert_mock.assert_not_awaited()
    delete_mock.assert_not_awaited()
