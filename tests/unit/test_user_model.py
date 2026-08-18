"""Tests for the User model."""

from sqlalchemy import Table

from app.models.user import User


def test_user_table_name() -> None:
    assert User.__tablename__ == "users"


def test_user_auth_identity_is_unique_together() -> None:
    table = User.__table__
    assert isinstance(table, Table)
    constraint_names = {c.name for c in table.constraints}
    assert "uq_user_auth_identity" in constraint_names


def test_user_required_fields_are_not_nullable() -> None:
    columns = User.__table__.columns
    for name in [
        "id",
        "auth_provider",
        "auth_provider_id",
        "locale",
        "role",
        "created_at",
    ]:
        assert columns[name].nullable is False, name


def test_user_optional_profile_fields_are_nullable() -> None:
    columns = User.__table__.columns
    for name in [
        "username",
        "email",
        "bio",
        "avatar_url",
        "city",
        "country_code",
        "timezone",
    ]:
        assert columns[name].nullable is True, name
