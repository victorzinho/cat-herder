from datetime import datetime
from typing import Protocol

from cat_herder.domain.ticket import Ticket


class TicketSource(Protocol):
    """A ticket system, such as Jira. Everything is in domain terms; keys are the source's own, unqualified."""

    @property
    def slug(self) -> str:
        """The source's slug in the config."""
        ...

    def fetch_ticket(self, key: str) -> Ticket:
        """Fetch the ticket with all its comments, attachments, links, children and Changes.

        Raises:
            SourceUnreachable: if the source can't be reached.
            TicketNotFound: if the source has no ticket with that key.
            SourceError: if the source answers with any other error.
        """
        ...

    def fetch_tickets(self, space: str, updated_since: datetime | None) -> list[Ticket]:
        """Fetch the space's tickets updated since then, or all of them, each as fetch_ticket would.

        Raises:
            SourceUnreachable: if the source can't be reached.
            SourceError: if the source answers with an error.
        """
        ...
