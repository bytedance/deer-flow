"""Optional shared type mapping; applications own their declarative base and models."""

from sqlalchemy import Text
from sqlalchemy.dialects.mysql import LONGTEXT

LONG_TEXT = Text().with_variant(LONGTEXT(), "mysql")
