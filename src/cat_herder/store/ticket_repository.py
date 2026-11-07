import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Integer, Table, UniqueConstraint, delete, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from cat_herder.domain.ticket import Attachment, Change, Comment, Link, Ticket, TicketSummary
from cat_herder.store.base import Base
from cat_herder.store.sprint_repository import SprintRepository, SprintRow, sprint_to_domain

ticket_sprints = Table(
    'ticket_sprints',
    Base.metadata,
    Column('ticket_id', Integer, ForeignKey('tickets.id', ondelete='CASCADE'), primary_key=True),
    Column('sprint_id', Integer, ForeignKey('sprints.id', ondelete='CASCADE'), primary_key=True),
)


class TicketRow(Base):
    """A full ticket, or a partial one known only through another: then only key, title, status and type are set."""

    __tablename__ = 'tickets'
    __table_args__ = (UniqueConstraint('source', 'key'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str]
    key: Mapped[str]
    title: Mapped[str]
    status: Mapped[str]
    type: Mapped[str]
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('tickets.id', ondelete='SET NULL'))
    fetched_at: Mapped[datetime | None]
    space: Mapped[str | None]
    description: Mapped[str | None]
    labels: Mapped[list[str] | None]
    components: Mapped[list[str] | None]
    assignee: Mapped[str | None]
    points: Mapped[float | None]
    estimated_hours: Mapped[float | None]
    created: Mapped[datetime | None]
    updated: Mapped[datetime | None]
    custom_fields: Mapped[dict[str, Any] | None]

    parent: Mapped['TicketRow | None'] = relationship(remote_side='TicketRow.id', back_populates='children')
    children: Mapped[list['TicketRow']] = relationship(back_populates='parent')
    sprints: Mapped[list[SprintRow]] = relationship(secondary=ticket_sprints)
    comments: Mapped[list['CommentRow']] = relationship(order_by='CommentRow.id', cascade='all, delete-orphan')
    attachments: Mapped[list['AttachmentRow']] = relationship(
        order_by='AttachmentRow.id', cascade='all, delete-orphan'
    )
    changes: Mapped[list['ChangeRow']] = relationship(order_by='ChangeRow.id', cascade='all, delete-orphan')


class CommentRow(Base):
    __tablename__ = 'comments'

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id', ondelete='CASCADE'))
    author: Mapped[str | None]
    created: Mapped[datetime]
    body: Mapped[str]


class AttachmentRow(Base):
    __tablename__ = 'attachments'

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id', ondelete='CASCADE'))
    source_id: Mapped[str]
    filename: Mapped[str]
    size: Mapped[int]
    created: Mapped[datetime]


class ChangeRow(Base):
    __tablename__ = 'changes'

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id', ondelete='CASCADE'))
    field: Mapped[str]
    author: Mapped[str | None]
    before: Mapped[str | None]
    after: Mapped[str | None]
    date: Mapped[datetime]


class LinkRow(Base):
    __tablename__ = 'links'
    __table_args__ = (UniqueConstraint('from_id', 'relation', 'to_id'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    from_id: Mapped[int] = mapped_column(ForeignKey('tickets.id', ondelete='CASCADE'))
    relation: Mapped[str]
    to_id: Mapped[int] = mapped_column(ForeignKey('tickets.id', ondelete='CASCADE'))

    from_ticket: Mapped[TicketRow] = relationship(foreign_keys=[from_id])
    to_ticket: Mapped[TicketRow] = relationship(foreign_keys=[to_id])


@dataclass(frozen=True, kw_only=True)
class StoredTicket:
    ticket: Ticket
    fetched_at: datetime


class TicketRepository:
    """Tickets in the local copy. A ticket known only through another one is partial, and reads as missing."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._sprint_repository = SprintRepository(session)

    def save(self, ticket: Ticket, fetched_at: datetime) -> None:
        """Store the ticket as fetched, replacing what was stored for it, and the tickets it mentions as partial.

        Links touching the ticket are replaced, and stored tickets that had it as parent but aren't among its children
        lose that parent.
        """
        row = self._upsert(ticket.source, ticket.key, ticket.title, ticket.status, ticket.type)
        _update_ticket_row(row, ticket)
        row.fetched_at = fetched_at
        row.sprints = [self._sprint_repository.save(sprint) for sprint in ticket.sprints]
        row.changes = [_change_from_domain(change) for change in ticket.changes]
        row.parent = self._save_summary(ticket.parent) if ticket.parent else None
        row.children = [self._save_summary(child) for child in ticket.children]

        rows_by_key = {ticket.key: row} | {linked.key: self._save_summary(linked) for linked in ticket.linked}
        self._session.flush()
        self._session.execute(delete(LinkRow).where(or_(LinkRow.from_id == row.id, LinkRow.to_id == row.id)))
        self._session.add_all(
            LinkRow(from_ticket=rows_by_key[link.from_key], relation=link.relation, to_ticket=rows_by_key[link.to_key])
            for link in ticket.links
        )
        self._session.flush()

    def get(self, source: str, key: str) -> StoredTicket | None:
        """Return the stored ticket, with its children derived from their parent, or None if it isn't stored in full."""
        row = self._row(source, key)
        if not row or not row.fetched_at:
            return None
        links = self._session.scalars(
            select(LinkRow).where(or_(LinkRow.from_id == row.id, LinkRow.to_id == row.id)).order_by(LinkRow.id)
        ).all()
        return StoredTicket(ticket=_ticket_from_rows(row, links), fetched_at=row.fetched_at)

    def _row(self, source: str, key: str) -> TicketRow | None:
        return self._session.scalars(select(TicketRow).where(TicketRow.source == source, TicketRow.key == key)).first()

    def _upsert(self, source: str, key: str, title: str, status: str, type: str) -> TicketRow:
        row = self._row(source, key)
        if not row:
            row = TicketRow(source=source, key=key, title=title, status=status, type=type)
            self._session.add(row)
        row.title, row.status, row.type = title, status, type
        return row

    def _save_summary(self, summary: TicketSummary) -> TicketRow:
        return self._upsert(summary.source, summary.key, summary.title, summary.status, summary.type)


def _ticket_from_rows(row: TicketRow, links: Sequence[LinkRow]) -> Ticket:
    # Only full tickets get here, and those have every column a Ticket requires.
    # Links are the ones touching the ticket, from either end.
    assert row.space and row.created and row.updated
    return Ticket(
        source=row.source,
        key=row.key,
        space=row.space,
        title=row.title,
        type=row.type,
        status=row.status,
        created=row.created,
        updated=row.updated,
        description=row.description,
        labels=tuple(row.labels or ()),
        components=tuple(row.components or ()),
        assignee=row.assignee,
        points=row.points,
        estimated_hours=row.estimated_hours,
        sprints=tuple(sprint_to_domain(sprint) for sprint in row.sprints),
        custom_fields=dict(row.custom_fields or {}),
        comments=tuple(_comment_to_domain(comment) for comment in row.comments),
        attachments=tuple(_attachment_to_domain(attachment) for attachment in row.attachments),
        parent=_summary_to_domain(row.parent) if row.parent else None,
        children=tuple(_summary_to_domain(child) for child in sorted(row.children, key=_key_order)),
        links=tuple(_link_to_domain(link) for link in links),
        linked=tuple(
            _summary_to_domain(link.to_ticket if link.from_id == row.id else link.from_ticket) for link in links
        ),
        changes=tuple(_change_to_domain(change) for change in row.changes),
    )


def _update_ticket_row(row: TicketRow, ticket: Ticket) -> None:
    # Sprints and the parent are left to the caller, as they're rows saved on their own.
    row.space = ticket.space
    row.description = ticket.description
    row.labels = list(ticket.labels)
    row.components = list(ticket.components)
    row.assignee = ticket.assignee
    row.points = ticket.points
    row.estimated_hours = ticket.estimated_hours
    row.created = ticket.created
    row.updated = ticket.updated
    row.custom_fields = dict(ticket.custom_fields)
    row.comments = [_comment_from_domain(comment) for comment in ticket.comments]
    row.attachments = [_attachment_from_domain(attachment) for attachment in ticket.attachments]


def _summary_to_domain(row: TicketRow) -> TicketSummary:
    return TicketSummary(source=row.source, key=row.key, title=row.title, status=row.status, type=row.type)


def _comment_to_domain(row: CommentRow) -> Comment:
    return Comment(author=row.author, created=row.created, body=row.body)


def _comment_from_domain(comment: Comment) -> CommentRow:
    return CommentRow(author=comment.author, created=comment.created, body=comment.body)


def _attachment_to_domain(row: AttachmentRow) -> Attachment:
    return Attachment(id=row.source_id, filename=row.filename, size=row.size, created=row.created)


def _attachment_from_domain(attachment: Attachment) -> AttachmentRow:
    return AttachmentRow(
        source_id=attachment.id, filename=attachment.filename, size=attachment.size, created=attachment.created
    )


def _change_to_domain(row: ChangeRow) -> Change:
    return Change(field=row.field, author=row.author, before=row.before, after=row.after, date=row.date)


def _change_from_domain(change: Change) -> ChangeRow:
    return ChangeRow(
        field=change.field, author=change.author, before=change.before, after=change.after, date=change.date
    )


def _link_to_domain(row: LinkRow) -> Link:
    return Link(from_key=row.from_ticket.key, relation=row.relation, to_key=row.to_ticket.key)


def _key_order(row: TicketRow) -> tuple[str | int, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r'(\d+)', row.key))
