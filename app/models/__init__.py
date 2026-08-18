"""SQLAlchemy ORM models. Each resource lives in its own module."""

from app.models.base import Base
from app.models.checkin import Checkin
from app.models.checkin_bookmark import CheckinBookmark
from app.models.checkin_like import CheckinLike
from app.models.checkin_product import CheckinProduct
from app.models.close_friend import CloseFriend
from app.models.follow import Follow
from app.models.global_product_type import (
    GlobalProductType,
    GlobalProductTypeTranslation,
)
from app.models.list import List
from app.models.list_bookmark import ListBookmark
from app.models.list_item import ListItem
from app.models.list_like import ListLike
from app.models.notification import (
    Notification,
    NotificationTargetType,
    NotificationType,
)
from app.models.product import Product
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.models.venue_category import VenueCategory, VenueCategoryTranslation
from app.models.venue_save import VenueSave, VenueSaveType

__all__ = [
    "Base",
    "Checkin",
    "CheckinBookmark",
    "CheckinLike",
    "CheckinProduct",
    "CloseFriend",
    "Follow",
    "GlobalProductType",
    "GlobalProductTypeTranslation",
    "List",
    "ListBookmark",
    "ListItem",
    "ListLike",
    "Notification",
    "NotificationTargetType",
    "NotificationType",
    "Product",
    "User",
    "UserRole",
    "Venue",
    "VenueCategory",
    "VenueCategoryTranslation",
    "VenueSave",
    "VenueSaveType",
]
