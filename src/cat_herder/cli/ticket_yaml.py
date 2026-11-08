from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from cat_herder.cli.yaml_format import NO_TIME_SOURCE, Block, dump, hours, load, number, timestamp
from cat_herder.domain.config import Config, TicketOrigin
from cat_herder.domain.ticket import Change, Comment, Link, Sprint, Ticket, TicketSummary

_SCHEMA: dict[str, Any] = yaml.safe_load(files('cat_herder.cli').joinpath('schemas', 'ticket.schema.yaml').read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER)
_READ_ONLY = {name for name, field in _SCHEMA['properties'].items() if field.get('readOnly')}
_READ_ONLY_IN_EDIT = _READ_ONLY | {'project'}
_REPLACED_WHOLE = {'sprints', 'labels', 'components'}


class TicketYamlError(Exception):
    """Ticket YAML that can't be used. The message says why."""


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
    return dump(_shown(ticket, config, spent_hours, brief, changes))


def tickets_to_yaml(tickets: Iterable[Ticket], config: Config) -> str:
    """The tickets as list shows them: some of the ticket schema's fields, with the same names and rules."""
    return dump([_listed(config, ticket) for ticket in tickets])


def read_ticket_yaml(text: str) -> dict[str, Any]:
    """The ticket YAML as a document, checked against the ticket schema.

    Raises:
        TicketYamlError: if it isn't YAML, or breaks the schema.
    """
    try:
        document = load(text)
    except yaml.YAMLError as error:
        raise TicketYamlError(str(error)) from error
    # types-jsonschema leaves one parameter of iter_errors' deprecated overload untyped.
    errors = _VALIDATOR.iter_errors(document)  # pyright: ignore[reportUnknownMemberType]
    problems = sorted(f'{error.json_path}: {error.message}' for error in errors)
    if problems:
        raise TicketYamlError('\n'.join(problems))
    return document


def ticket_origin(document: Mapping[str, Any], config: Config) -> TicketOrigin:
    """The source and space of the document's project, where a ticket is created.

    Raises:
        TicketYamlError: if the document has no project, or its project isn't configured or has no ticket source.
    """
    if 'project' not in document:
        raise TicketYamlError('project is required to create a ticket')
    try:
        project = config.project(document['project'])
    except KeyError:
        raise TicketYamlError(f'{document["project"]} is not in projects') from None
    if not project.tickets:
        raise TicketYamlError(f'{project.slug} has no ticket source')
    return project.tickets


def new_ticket(
    document: Mapping[str, Any], origin: TicketOrigin, config: Config, sprint_by_name: Mapping[str, Sprint]
) -> Ticket:
    """The ticket the document describes, to create in the origin's space.

    Its key is empty, and so are the link ends left out, which stand for it. Its dates are now, and its status is
    empty unless the document gives one.

    Args:
        document: a ticket YAML document, with any of its writable fields.
        origin: the source and space to create it in.
        config: the people to read the document with.
        sprint_by_name: the source's sprints that the document can name.

    Raises:
        TicketYamlError: if the document has a read-only field, or names a person or sprint that can't be written.
    """
    no_ticket: dict[str, Any] = {'parent': None, 'links': []}
    read_only = sorted([*document.keys() & _READ_ONLY, *_read_only_inside(document, no_ticket)])
    if read_only:
        raise TicketYamlError(f'read-only fields can\'t be set when creating: {", ".join(read_only)}')
    now = datetime.now(UTC)
    assignee = document.get('assignee')
    parent = document.get('parent')
    return Ticket(
        source=origin.source,
        key='',
        space=origin.space,
        title=document.get('title', ''),
        type=document.get('type', ''),
        status=document.get('status', ''),
        created=now,
        updated=now,
        description=document.get('description'),
        labels=tuple(document.get('labels', [])),
        components=tuple(document.get('components', [])),
        assignee=_identity(config, origin.source, assignee) if assignee else None,
        points=document.get('points'),
        estimated_hours=document.get('estimated_hours'),
        sprints=tuple(_sprint(sprint_by_name, name) for name in document.get('sprints', [])),
        custom_fields=dict(document.get('custom_fields', {})),
        parent=parent['key'] if parent else None,
        links=tuple(
            Link(from_key=link.get('from', ''), relation=link['relation'], to_key=link.get('to', ''))
            for link in document.get('links', [])
        ),
    )


def edited_ticket(
    document: Mapping[str, Any],
    ticket: Ticket,
    config: Config,
    sprint_by_name: Mapping[str, Sprint],
) -> Ticket:
    """The ticket with the fields in the document that differ from it.

    Args:
        document: a ticket YAML document, with any of its fields.
        ticket: the ticket as its source has it.
        config: the people and projects to read the document with.
        sprint_by_name: the source's sprints that the document can name.

    Raises:
        TicketYamlError: if a read-only field differs, or the document names a person, sprint or custom field
            that can't be written.
    """
    shown = _shown(ticket, config, spent_hours=None, brief=False, changes=True)
    different = {
        name: value
        for name, value in document.items()
        if name not in {'spent_hours'} and not _same(name, value, shown[name])
    }
    read_only = sorted([*different.keys() & _READ_ONLY_IN_EDIT, *_read_only_inside(document, shown)])
    if read_only:
        raise TicketYamlError(f'{shown["key"]} has read-only fields that differ: {", ".join(read_only)}')

    values: dict[str, Any] = {}
    for name, value in different.items():
        match name:
            case 'assignee':
                values[name] = _identity(config, ticket.source, value) if value is not None else None
            case 'custom_fields':
                values[name] = ticket.custom_fields | _custom_fields(value, shown[name])
            case 'parent':
                values[name] = value['key'] if value else None
            case 'sprints':
                values[name] = tuple(_sprint(sprint_by_name, sprint_name) for sprint_name in value)
            case 'links':
                values[name] = tuple(_link_from_yaml(link) for link in value)
            case 'labels' | 'components':
                values[name] = tuple(value)
            case _:
                values[name] = value
    return replace(ticket, **values)


def _shown(ticket: Ticket, config: Config, spent_hours: float | None, brief: bool, changes: bool) -> dict[str, Any]:
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
        'parent': _reference(_related(ticket, ticket.parent)) if ticket.parent else None,
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
    return document


def _same(name: str, value: Any, shown: Any) -> bool:
    match name:
        case 'custom_fields':
            return all(shown.get(custom_name) == custom_value for custom_name, custom_value in value.items())
        case 'parent':
            return (value and value['key']) == (shown and shown['key'])
        case 'links':
            return {_sentence(link) for link in value} == {_sentence(link) for link in shown}
        case _ if name in _REPLACED_WHOLE:
            return sorted(value) == sorted(shown)
        case _:
            return value == shown


def _read_only_inside(document: Mapping[str, Any], shown: Mapping[str, Any]) -> list[str]:
    # The status and title of the parent and the linked tickets, as they are now.
    differ: list[str] = []
    if parent := document.get('parent'):
        same_parent = shown['parent'] and shown['parent']['key'] == parent['key']
        shown_parent: Mapping[str, Any] = shown['parent'] if same_parent else {}
        differ += _differing('parent', parent, shown_parent, ('status', 'title'))
    shown_link_by_sentence = {_sentence(link): link for link in shown['links']}
    for link in document.get('links', []):
        shown_link = shown_link_by_sentence.get(_sentence(link), {})
        differ += _differing('links', link, shown_link, ('other_status', 'other_title'))
    return differ


def _differing(prefix: str, document: Mapping[str, Any], shown: Mapping[str, Any], names: Iterable[str]) -> list[str]:
    return [f'{prefix}.{name}' for name in names if name in document and document[name] != shown.get(name)]


def _sentence(link: Mapping[str, str]) -> tuple[str | None, str, str | None]:
    return link.get('from'), link['relation'], link.get('to')


def _identity(config: Config, source: str, person_slug: str) -> str:
    try:
        identity = config.person(person_slug).identity_by_source.get(source)
    except KeyError:
        raise TicketYamlError(f'{person_slug} is not in people') from None
    if identity is None:
        raise TicketYamlError(f'{person_slug} has no identity in {source}')
    return str(identity)


def _custom_fields(document: Mapping[str, Any], shown: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(document.keys() - shown.keys())
    if unknown:
        raise TicketYamlError(f'custom fields not in the config: {", ".join(unknown)}')
    return {name: value for name, value in document.items() if value != shown[name]}


def _sprint(sprint_by_name: Mapping[str, Sprint], name: str) -> Sprint:
    if name not in sprint_by_name:
        raise TicketYamlError(f'no sprint {name} in the local copy')
    return sprint_by_name[name]


def _link_from_yaml(link: Mapping[str, str]) -> Link:
    if 'from' not in link or 'to' not in link:
        raise TicketYamlError(f'links need from and to when editing: {link}')
    return Link(from_key=link['from'], relation=link['relation'], to_key=link['to'])


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


def _related(ticket: Ticket, key: str) -> TicketSummary:
    return next(summary for summary in ticket.related_summaries if summary.key == key)


def _reference(summary: TicketSummary) -> dict[str, str]:
    return {'key': summary.key, 'status': summary.status, 'title': summary.title}


def _link(ticket: Ticket, link: Link) -> dict[str, str]:
    other_key = link.to_key if link.from_key == ticket.key else link.from_key
    other = _related(ticket, other_key)
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
