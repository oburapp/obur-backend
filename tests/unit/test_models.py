"""Tests for the shared SQLAlchemy declarative base."""

from sqlalchemy.orm import DeclarativeBase

from app.models import Base


def test_base_is_a_sqlalchemy_declarative_base() -> None:
    assert issubclass(Base, DeclarativeBase)
