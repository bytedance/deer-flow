import zoneinfo
from datetime import datetime
from datetime import timezone as datetime_timezone

from store.config.app_config import get_app_config

# IANA identifiers that map to UTC — see https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
_UTC_IDENTIFIERS = frozenset({"Etc/UCT", "Etc/Universal", "Etc/UTC", "Etc/Zulu", "UCT", "Universal", "UTC", "Zulu"})


class TimeZone:
    def __init__(self) -> None:
        app_config = get_app_config()
        if app_config.timezone in _UTC_IDENTIFIERS:
            self.tz_info = datetime_timezone.utc
        else:
            self.tz_info = zoneinfo.ZoneInfo(app_config.timezone)

    def now(self) -> datetime:
        """Return the current time in the configured timezone."""
        return datetime.now(self.tz_info)

    def from_datetime(self, t: datetime) -> datetime:
        """Convert a datetime to the configured timezone."""
        return t.astimezone(self.tz_info)

    def from_str(self, t_str: str, format_str: str = "%Y-%m-%d %H:%M:%S") -> datetime:
        """Parse a time string and attach the configured timezone."""
        return datetime.strptime(t_str, format_str).replace(tzinfo=self.tz_info)

    @staticmethod
    def to_str(t: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Format a datetime to string."""
        return t.strftime(format_str)

    @staticmethod
    def to_utc(t: datetime | int) -> datetime:
        """Convert a datetime or Unix timestamp to UTC."""
        if isinstance(t, datetime):
            return t.astimezone(datetime_timezone.utc)
        return datetime.fromtimestamp(t, tz=datetime_timezone.utc)


_timezone = None


def get_timezone() -> TimeZone:
    """Return the global TimeZone singleton (lazy-initialized)."""
    global _timezone
    if _timezone is None:
        _timezone = TimeZone()
    return _timezone
