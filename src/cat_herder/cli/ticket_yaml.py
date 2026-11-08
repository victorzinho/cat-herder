from collections.abc import Iterable
from typing import Any

from cat_herder.cli.yaml_output import NO_TIME_SOURCE, Block, dump, hours, number, timestamp
from cat_herder.domain.config import Config
from cat_herder.domain.ticket import Change, Comment, Link, Ticket, TicketSummary


def ticket_to_yaml(
    ticket: Ticket,
    config: Config,
    spent_hours: float | None = None,
    brief: bool = False,
    changes: bool = False
) -> str:
    """The ticket in the ticket schema's shape. brief leaves out comments and attachments; changes adds Changes.

    The key is qualified, as in jira:SAT-7, when its space is in several ticket sources.
    """
    project = config.project_of_ticket(ticket)
    document: dict[str, Any] = {
        'key': _key(config, ticket),
        'title': ticket.title,
        'project': project.slug if project else None,
        'type': ticket.type,
        'status': ticket.status,
        'assignee': config.person_name(ticket.source, ticket.assignee) if ticket.assignee else None,
        'points': number(ticket.points),
        'estimated_hours': number(ticket.estimated_hours),
        'custom_fields': {name: number(value) for name, value in ticket.custom_fields.items()},
        'spent_hours': hours(spent_hours) if project and project.time else NO_TIME_SOURCE,
        'parent': _reference(ticket.parent) if ticket.parent else None,
        'children': [_reference(child) for child in ticket.children],
        'sprints': [sprint.name for sprint in ticket.sprints],
        'labels': list(ticket.labels),
        'components': list(ticket.components),
        'created': timestamp(ticket.created),
        'updated': timestamp(ticket.updated),
        'description': ticket.description,
        'links': [_link(ticket, link) for link in ticket.links],
    }
    if not brief:
        document['comments'] = [_comment(config, ticket.source, comment) for comment in ticket.comments]
        document['attachments'] = [
            {
                'filename': attachment.filename,
                'size': attachment.size,
                'created': timestamp(attachment.created),
                'path': None,
            }
            for attachment in ticket.attachments
        ]
    if changes:
        document['changes'] = [_change(config, ticket.source, change) for change in ticket.changes]
    return dump(document)


def tickets_to_yaml(tickets: Iterable[Ticket], config: Config) -> str:
    """The tickets as list shows them: some of the ticket schema's fields, with the same names and rules."""
    return dump([_listed(config, ticket) for ticket in tickets])


def _listed(config: Config, ticket: Ticket) -> dict[str, Any]:
    project = config.project_of_ticket(ticket)
    return {
        'key': _key(config, ticket),
        'title': ticket.title,
        'project': project.slug if project else None,
        'type': ticket.type,
        'status': ticket.status,
        'assignee': config.person_name(ticket.source, ticket.assignee) if ticket.assignee else None,
        'points': number(ticket.points),
        'estimated_hours': number(ticket.estimated_hours),
        'custom_fields': {name: number(value) for name, value in ticket.custom_fields.items()},
        'sprints': [sprint.name for sprint in ticket.sprints],
        'updated': timestamp(ticket.updated),
    }


def _key(config: Config, ticket: Ticket) -> str:
    qualified = len(config.ticket_sources_for_key_prefix(ticket.space)) > 1
    return f'{ticket.source}:{ticket.key}' if qualified else ticket.key


def _reference(summary: TicketSummary) -> dict[str, str]:
    return {'key': summary.key, 'status': summary.status, 'title': summary.title}


def _link(ticket: Ticket, link: Link) -> dict[str, str]:
    other_key = link.to_key if link.from_key == ticket.key else link.from_key
    other = next(summary for summary in ticket.linked if summary.key == other_key)
    return {
        'from': link.from_key,
        'relation': link.relation,
        'to': link.to_key,
        'other_status': other.status,
        'other_title': other.title,
    }


def _comment(config: Config, source: str, comment: Comment) -> Block:
    return Block(author=config.person_name(source, comment.author), date=timestamp(comment.created), body=comment.body)


def _change(config: Config, source: str, change: Change) -> Block:
    before, after = change.before, change.after
    if change.field == 'assignee':
        before = config.person_name(source, before) if before else None
        after = config.person_name(source, after) if after else None
    return Block(
        {
            'field': change.field,
            'person': config.person_name(source, change.author),
            'from': before,
            'to': after,
            'date': timestamp(change.date),
        }
    )

