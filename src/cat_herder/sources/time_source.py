from collections.abc import Collection
from datetime import datetime
from typing import Protocol

from cat_herder.domain.time_entry import TimeEntry


class TimeSource(Protocol):
    """A time system, such as Toggl. Everything is in domain terms."""

    @property
    def slug(self) -> str:
        """The source's slug in the config."""
        ...

    @property
    def max_fetch_days(self) -> int:
        """The most days fetch_time_entries can cover in one call."""
        ...

    def fetch_time_entries(self, spaces: Collection[str], start: datetime, end: datetime) -> list[TimeEntry]:
        """Fetch the spaces' finished entries starting from start until before end, at most max_fetch_days apart.

        Raises:
            SourceUnreachable: if the source can't be reached.
            SourceError: if the source answers with an error, or doesn't have one of the spaces.
        """
        ...
