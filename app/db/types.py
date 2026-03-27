"""Cross-database column types that work on both SQLite and PostgreSQL."""

import uuid

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import String, TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses String(36) on SQLite, native UUID on PostgreSQL.
    Stores as hyphenated string everywhere so SQLite can query it.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


JSON = SA_JSON().with_variant(SA_JSON(none_as_null=True), "sqlite")
