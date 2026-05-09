"""Re-export all models so Alembic can discover them."""
from app.models.user import User, UserRole
from app.models.apartment import Apartment
from app.models.listing import (
    ListingSource,
    ApartmentImage,
    ApartmentSnapshot,
    ApartmentChange,
)
from app.models.rating import RatingCategory, ApartmentRating
from app.models.status import (
    UserApartmentStatus,
    UserApartmentNote,
    StatusEnum,
)
from app.models.tag import Tag, apartment_tags
from app.models.location import TargetAddress, TravelTime, TravelMode
from app.models.job import ImportJob, ImportJobStatus
from app.models.duplicate import DuplicateCandidate, DuplicateStatus
from app.models.settings import AppSetting
from app.models.audit import AuditLog


__all__ = [
    "User",
    "UserRole",
    "Apartment",
    "ListingSource",
    "ApartmentImage",
    "ApartmentSnapshot",
    "ApartmentChange",
    "RatingCategory",
    "ApartmentRating",
    "UserApartmentStatus",
    "UserApartmentNote",
    "StatusEnum",
    "Tag",
    "apartment_tags",
    "TargetAddress",
    "TravelTime",
    "TravelMode",
    "ImportJob",
    "ImportJobStatus",
    "DuplicateCandidate",
    "DuplicateStatus",
    "AppSetting",
    "AuditLog",
]
