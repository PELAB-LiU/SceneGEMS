"""Declarative base and the column types every table shares.

Constraint names follow one convention, so migrations can name what they drop. Enums are
stored as strings with a CHECK constraint instead of native Postgres enums, so adding a
value is a plain constraint change in a migration.
"""

from enum import Enum
from typing import Type

from sqlalchemy import DateTime
from sqlalchemy import Enum as EnumType
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_class: Type[Enum], constraint_name: str) -> EnumType:
    """A string column limited to the enum's values; rows hold the value, not the member name."""
    return EnumType(
        enum_class,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        length=32,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def utc_timestamp() -> DateTime:
    return DateTime(timezone=True)
