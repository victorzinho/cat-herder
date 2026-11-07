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
