from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import yaml

from cat_herder.domain.config import Config
from cat_herder.domain.ticket import Change, Comment, CustomValue, Link, Ticket, TicketSummary

NO_TIME_SOURCE = 'no time source'
UNKNOWN_PERSON = 'unknown'


def ticket_to_yaml(ticket: Ticket, config: Config, brief: bool = False, changes: bool = False) -> str:
    """The ticket in the ticket schema's shape. brief leaves out comments and attachments; changes adds Changes.

    The key is qualified, as in jira:SAT-7, when its space is in several ticket sources. Spent hours are null until
    time entries are stored.
    """
    person_by_identity = _person_by_identity(config, ticket.source)
    project = config.project_for(ticket.source, ticket.space)
    document: dict[str, Any] = {
        'key': _key(config, ticket),
        'title': ticket.title,
        'project': project.slug if project else None,
        'type': ticket.type,
        'status': ticket.status,
        'assignee': _person(person_by_identity, ticket.assignee) if ticket.assignee else None,
        'points': _number(ticket.points),
        'estimated_hours': _number(ticket.estimated_hours),
        'custom_fields': {name: _number(value) for name, value in ticket.custom_fields.items()},
        'spent_hours': None if project and project.time else NO_TIME_SOURCE,
        'parent': _reference(ticket.parent) if ticket.parent else None,
        'children': [_reference(child) for child in ticket.children],
        'sprints': [sprint.name for sprint in ticket.sprints],
        'labels': list(ticket.labels),
        'components': list(ticket.components),
        'created': _date(ticket.created),
        'updated': _date(ticket.updated),
        'description': ticket.description,
        'links': [_link(ticket, link) for link in ticket.links],
    }
    if not brief:
        document['comments'] = [_comment(person_by_identity, comment) for comment in ticket.comments]
        document['attachments'] = [
            {
                'filename': attachment.filename,
                'size': attachment.size,
                'created': _date(attachment.created),
                'path': None,
            }
            for attachment in ticket.attachments
        ]
    if changes:
        document['changes'] = [_change(person_by_identity, change) for change in ticket.changes]
    return _dump(document)


def tickets_to_yaml(tickets: Iterable[Ticket], config: Config) -> str:
    """The tickets as list shows them: some of the ticket schema's fields, with the same names and rules."""
    return _dump([_listed(config, ticket) for ticket in tickets])


class _Dumper(yaml.SafeDumper):
    # Indents list items under their key, as in the docs' examples.
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


class _Block(dict[str, Any]):
    """A mapping dumped in block style, so its multi-line values can be literal blocks."""


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    # types-PyYAML leaves represent_scalar's value untyped.
    style = '|' if '\n' in value else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style)  # pyright: ignore[reportUnknownMemberType]


def _represent_block(dumper: yaml.SafeDumper, value: _Block) -> yaml.MappingNode:
    return dumper.represent_mapping('tag:yaml.org,2002:map', value, flow_style=False)


_Dumper.add_representer(str, _represent_str)
_Dumper.add_representer(_Block, _represent_block)


def _dump(document: object) -> str:
    return yaml.dump(document, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000)


def _listed(config: Config, ticket: Ticket) -> dict[str, Any]:
    project = config.project_for(ticket.source, ticket.space)
    return {
        'key': _key(config, ticket),
        'title': ticket.title,
        'project': project.slug if project else None,
        'type': ticket.type,
        'status': ticket.status,
        'assignee': _person(_person_by_identity(config, ticket.source), ticket.assignee) if ticket.assignee else None,
        'points': _number(ticket.points),
        'estimated_hours': _number(ticket.estimated_hours),
        'custom_fields': {name: _number(value) for name, value in ticket.custom_fields.items()},
        'sprints': [sprint.name for sprint in ticket.sprints],
        'updated': _date(ticket.updated),
    }


def _key(config: Config, ticket: Ticket) -> str:
    qualified = len(config.sources_for_key_prefix(ticket.space)) > 1
    return f'{ticket.source}:{ticket.key}' if qualified else ticket.key


def _person_by_identity(config: Config, source: str) -> dict[str, str]:
    return {
        str(identity): person.slug
        for person in config.people
        if (identity := person.identity_by_source.get(source)) is not None
    }


def _person(person_by_identity: dict[str, str], identity: str | None) -> str:
    if identity is None:
        return UNKNOWN_PERSON
    return person_by_identity.get(identity) or f'{UNKNOWN_PERSON} ({identity})'


def _number(value: CustomValue) -> CustomValue | int:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _date(value: datetime) -> str:
    return value.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


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


def _comment(person_by_identity: dict[str, str], comment: Comment) -> _Block:
    return _Block(author=_person(person_by_identity, comment.author), date=_date(comment.created), body=comment.body)


def _change(person_by_identity: dict[str, str], change: Change) -> _Block:
    before, after = change.before, change.after
    if change.field == 'assignee':
        before = _person(person_by_identity, before) if before else None
        after = _person(person_by_identity, after) if after else None
    return _Block(
        {
            'field': change.field,
            'person': _person(person_by_identity, change.author),
            'from': before,
            'to': after,
            'date': _date(change.date),
        }
    )

