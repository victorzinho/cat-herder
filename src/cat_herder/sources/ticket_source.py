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

    def create_ticket(self, ticket: Ticket) -> str:
        """Create the ticket in its space, and return its key.

        Its key only stands for it in its links. The source sets its key and dates, its status when empty, and any
        field left empty, and ignores the rest of what a ticket YAML can't write. Values the source doesn't take are
        found before creating it, except a status no transition leads to.

        Raises:
            SourceUnreachable: if the source can't be reached before creating it.
            WriteIncomplete: if a call fails once it's created.
            SourceError: if the source doesn't take a value, or answers with any other error.
        """
        ...

    def update_ticket(self, edited: Ticket) -> None:
        """Write what differs between the edited ticket and the ticket as the source has it now.

        Only the fields a ticket YAML can write count. Calls go in the least error-prone order, and values the source
        doesn't take are found before any write.

        Raises:
            SourceUnreachable: if the source can't be reached before writing anything.
            TicketNotFound: if the source has no ticket with that key.
            WriteIncomplete: if a call that writes fails.
            SourceError: if the source doesn't take a value, or answers with any other error.
        """
        ...

    def add_comment(self, key: str, body: str) -> None:
        """Add a comment, in markdown, to the ticket.

        Raises:
            SourceUnreachable: if the source can't be reached.
            TicketNotFound: if the source has no ticket with that key.
            SourceError: if the source answers with any other error.
        """
        ...
