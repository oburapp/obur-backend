"""Tests for the Clerk webhook endpoint."""

from unittest.mock import AsyncMock

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


async def test_upsert_user_executes_an_insert_and_commits() -> None:
    data = ClerkUserData(
        id="user_abc",
        username="erenm",
        email_addresses=[ClerkEmailAddress(id="idn_1", email_address="e@example.com")],
        primary_email_address_id="idn_1",
        image_url="https://img.clerk.com/x",
    )
    session = AsyncMock()

    await _upsert_user(session, data)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_delete_user_executes_a_delete_and_commits() -> None:
    session = AsyncMock()

    await _delete_user(session, "user_abc")

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


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
