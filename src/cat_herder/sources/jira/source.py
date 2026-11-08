import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from urllib.parse import quote

from cat_herder.domain.config import JiraSourceConfig
from cat_herder.domain.ticket import CustomValue, Link, Sprint, SprintState, Ticket
from cat_herder.sources.errors import SourceError, SourceUnreachable, TicketNotFound, WriteIncomplete
from cat_herder.sources.jira import mapping
from cat_herder.sources.jira.adf import markdown_to_adf
from cat_herder.sources.jira.client import JiraClient, JiraNotFound, JsonObject

PAGE_SIZE = 100
# The ticket's fields that one edit call writes, in the order a failure reports them.
_FIELDS = (
    'title',
    'type',
    'assignee',
    'points',
    'estimated_hours',
    'custom_fields',
    'parent',
    'sprints',
    'labels',
    'components',
    'description',
)


class JiraSource:
    """A Jira Cloud instance, as a TicketSource."""

    def __init__(self, config: JiraSourceConfig, client: JiraClient) -> None:
        self._config = config
        self._client = client

    @property
    def slug(self) -> str:
        return self._config.slug

    def fetch_ticket(self, key: str) -> Ticket:
        """See TicketSource.fetch_ticket. A ticket moved to another space comes back with its new key."""
        issue = self._get_issue(key, tuple(mapping.ticket_fields(self._config)))
        current_key: str = issue['key']
        return mapping.ticket(
            self._config,
            issue,
            comments=self._pages(f'issue/{current_key}/comment', 'comments', {'orderBy': 'created'}),
            histories=self._pages(f'issue/{current_key}/changelog', 'values'),
            children=self._search(f'parent = "{current_key}" ORDER BY key', mapping.SUMMARY_FIELDS),
        )

    def fetch_tickets(self, space: str, updated_since: datetime | None) -> list[Ticket]:
        """See TicketSource.fetch_tickets. Comments and Changes come with the search, unless there are too many."""
        jql = f'project = "{space}"'
        if updated_since:
            # JQL reads absolute dates in the Jira user's time zone, and a relative one in minutes doesn't depend on it.
            minutes = math.ceil((datetime.now(UTC) - updated_since).total_seconds() / 60) + 1
            jql += f' AND updated >= -{minutes}m'
        fields = (*mapping.ticket_fields(self._config), 'comment')
        issues = self._search(f'{jql} ORDER BY key', fields, expand='changelog')
        children = self._children([issue['key'] for issue in issues])
        return [mapping.ticket(
            self._config,
            issue,
            comments=self._comments(issue),
            histories=self._histories(issue),
            children=children[issue['key']],
        ) for issue in issues]

    def update_ticket(self, edited: Ticket) -> None:
        """See TicketSource.update_ticket.

        Fields go in one call, then each link added and each one removed, and the status last, as reaching it can
        leave fields uneditable.
        """
        issue = self._get_issue(edited.key, tuple(mapping.ticket_fields(self._config)))
        current = mapping.ticket(self._config, issue, comments=[], histories=[], children=[])
        writes = [
            *self._field_writes(current, edited),
            *self._link_writes(issue, current, edited),
            *self._status_writes(current, edited),
        ]
        for done, write in enumerate(writes):
            try:
                write.call()
            except (SourceError, SourceUnreachable) as error:
                applied = ', '.join(write.description for write in writes[:done]) or 'nothing'
                not_applied = ', '.join(write.description for write in writes[done:])
                raise WriteIncomplete(f'{edited.key} got {applied}, and not {not_applied}: {error}') from error

    def add_comment(self, key: str, body: str) -> None:
        """See TicketSource.add_comment."""
        try:
            self._client.post(f'issue/{quote(key, safe="")}/comment', {'body': markdown_to_adf(body)})
        except JiraNotFound as error:
            raise TicketNotFound(f'{self._config.slug} has no ticket {key}') from error

    def _get_issue(self, key: str, fields: tuple[str, ...]) -> JsonObject:
        try:
            return self._client.get(f'issue/{quote(key, safe="")}', {'fields': ','.join(fields)})
        except JiraNotFound as error:
            raise TicketNotFound(f'{self._config.slug} has no ticket {key}') from error

    def _field_writes(self, ticket: Ticket, edited: Ticket) -> list['_Write']:
        changed = [name for name in _FIELDS if getattr(edited, name) != getattr(ticket, name)]
        fields: JsonObject = {}
        update: JsonObject = {}
        for name in changed:
            match name:
                case 'title':
                    fields['summary'] = edited.title
                case 'type':
                    fields['issuetype'] = {'name': edited.type}
                case 'assignee':
                    fields['assignee'] = {'accountId': edited.assignee} if edited.assignee else None
                case 'points':
                    fields[self._configured('points', self._config.points_field)] = edited.points
                case 'estimated_hours':
                    # Setting the field can't clear it, while editing time tracking can do both.
                    hours = edited.estimated_hours
                    estimate = '' if hours is None else f'{round(hours * 60)}m'
                    update['timetracking'] = [{'edit': {'originalEstimate': estimate}}]
                case 'custom_fields':
                    fields |= self._custom_fields(ticket, edited)
                case 'parent':
                    fields['parent'] = {'key': edited.parent} if edited.parent else None
                case 'sprints':
                    sprints_field = self._configured('sprints', self._config.sprints_field)
                    fields[sprints_field] = self._sprint_id(ticket.sprints, edited.sprints)
                case 'labels':
                    fields['labels'] = list(edited.labels)
                case 'components':
                    fields['components'] = [{'name': component} for component in edited.components]
                case _:
                    fields['description'] = markdown_to_adf(edited.description) if edited.description else None
        if not changed:
            return []
        body = {'fields': fields, 'update': update}
        return [_Write(', '.join(changed), partial(self._client.put, f'issue/{ticket.key}', body))]

    def _custom_fields(self, ticket: Ticket, edited: Ticket) -> JsonObject:
        changed = {
            name: value for name, value in edited.custom_fields.items() if value != ticket.custom_fields.get(name)
        }
        editable: JsonObject = self._client.get(f'issue/{quote(ticket.key, safe="")}/editmeta')['fields']
        fields: JsonObject = {}
        for name, value in changed.items():
            field_id = self._config.custom_fields[name]
            if field_id not in editable:
                raise SourceError(f'{self._config.slug} can\'t edit {name} in {ticket.key}')
            fields[field_id] = _custom_value(name, value, editable[field_id])
        return fields

    def _sprint_id(self, current: tuple[Sprint, ...], edited: tuple[Sprint, ...]) -> int | None:
        # Jira holds a ticket in one sprint that hasn't ended at most, and keeps the ended ones as they are.
        def ended(sprints: tuple[Sprint, ...]) -> set[str]:
            return {sprint.id for sprint in sprints if sprint.state is SprintState.ENDED}

        if ended(edited) != ended(current):
            raise SourceError(f'{self._config.slug} can\'t add or remove ended sprints')
        not_ended = [sprint for sprint in edited if sprint.state is not SprintState.ENDED]
        if len(not_ended) > 1:
            raise SourceError(f'{self._config.slug} holds a ticket in one sprint that hasn\'t ended at most')
        return int(not_ended[0].id) if not_ended else None

    def _link_writes(self, issue: JsonObject, ticket: Ticket, edited: Ticket) -> list['_Write']:
        added = sorted(set(edited.links) - set(ticket.links), key=_link_order)
        removed = sorted(set(ticket.links) - set(edited.links), key=_link_order)
        # Removing a link takes its ID, which only the issue's links carry.
        issue_links: list[JsonObject] = issue['fields']['issuelinks']
        id_by_link = {mapping.link(ticket.key, issue_link): issue_link['id'] for issue_link in issue_links}
        type_by_wording = self._link_type_by_wording() if added else {}
        writes: list[_Write] = []
        # Adding first, so that a failure loses no link.
        for link in added:
            if link.relation not in type_by_wording:
                wordings = ', '.join(sorted(type_by_wording))
                raise SourceError(f'{self._config.slug} has no relation {link.relation}, only: {wordings}')
            body = {
                'type': {'name': type_by_wording[link.relation]},
                'inwardIssue': {'key': link.from_key},
                'outwardIssue': {'key': link.to_key},
            }
            writes.append(_Write(f'link {_sentence(link)}', partial(self._client.post, 'issueLink', body)))
        for link in removed:
            unlink = partial(self._client.delete, f'issueLink/{id_by_link[link]}')
            writes.append(_Write(f'unlink {_sentence(link)}', unlink))
        return writes

    def _link_type_by_wording(self) -> dict[str, str]:
        types: list[JsonObject] = self._client.get('issueLinkType')['issueLinkTypes']
        return {link_type['outward']: link_type['name'] for link_type in types}

    def _status_writes(self, ticket: Ticket, edited: Ticket) -> list['_Write']:
        if edited.status == ticket.status:
            return []
        # Jira reaches a status through a transition, which depends on where the ticket is.
        key = ticket.key
        transitions: list[JsonObject] = self._client.get(f'issue/{quote(key, safe="")}/transitions')['transitions']
        transition = next((transition for transition in transitions if transition['to']['name'] == edited.status), None)
        if not transition:
            statuses = ', '.join(transition['to']['name'] for transition in transitions)
            raise SourceError(f'{key} can\'t go to {edited.status} in {self._config.slug}, only to: {statuses}')
        body = {'transition': {'id': transition['id']}}
        return [_Write(f'status {edited.status}', partial(self._client.post, f'issue/{key}/transitions', body))]

    def _configured(self, name: str, field_id: str | None) -> str:
        if not field_id:
            raise SourceError(f'{self._config.slug} has no {name} field in the config')
        return field_id

    def _comments(self, issue: JsonObject) -> list[JsonObject]:
        comment: JsonObject = issue['fields']['comment']
        if comment['total'] > len(comment['comments']):
            return self._pages(f'issue/{issue["key"]}/comment', 'comments', {'orderBy': 'created'})
        return comment['comments']

    def _histories(self, issue: JsonObject) -> list[JsonObject]:
        changelog: JsonObject = issue['changelog']
        if changelog['total'] > len(changelog['histories']):
            return self._pages(f'issue/{issue["key"]}/changelog', 'values')
        return changelog['histories']

    def _children(self, keys: list[str]) -> defaultdict[str, list[JsonObject]]:
        children: defaultdict[str, list[JsonObject]] = defaultdict(list)
        for start in range(0, len(keys), PAGE_SIZE):
            parents = ', '.join(f'"{key}"' for key in keys[start : start + PAGE_SIZE])
            for child in self._search(f'parent in ({parents}) ORDER BY key', (*mapping.SUMMARY_FIELDS, 'parent')):
                children[child['fields']['parent']['key']].append(child)
        return children

    def _pages(self, path: str, items_key: str, params: dict[str, str | int] | None = None) -> list[JsonObject]:
        items: list[JsonObject] = []
        while True:
            page = self._client.get(path, {**(params or {}), 'startAt': len(items), 'maxResults': PAGE_SIZE})
            items.extend(page[items_key])
            if not page[items_key] or len(items) >= page['total']:
                return items

    def _search(self, jql: str, fields: tuple[str, ...], expand: str | None = None) -> list[JsonObject]:
        issues: list[JsonObject] = []
        body: JsonObject = {'jql': jql, 'fields': list(fields), 'maxResults': PAGE_SIZE}
        if expand:
            body['expand'] = expand
        while True:
            page = self._client.post('search/jql', body)
            issues.extend(page['issues'])
            if not (token := page.get('nextPageToken')):
                return issues
            body = {**body, 'nextPageToken': token}


@dataclass(frozen=True)
class _Write:
    """One call that writes, and what it writes, for reporting."""

    description: str
    call: Callable[[], object]


def _custom_value(name: str, value: CustomValue, field: JsonObject) -> object:
    match field['schema']['type']:
        case 'option':
            allowed = [option['value'] for option in field.get('allowedValues', [])]
            if value is not None and value not in allowed:
                raise SourceError(f'{name} can\'t be {value}, only: {", ".join(allowed)}')
            return {'value': value} if value is not None else None
        case 'string' | 'number':
            return value
        case other:
            raise SourceError(f'{name} is a {other} field, but only single text, number or option values are carried')


def _link_order(link: Link) -> tuple[str, str, str]:
    return link.from_key, link.relation, link.to_key


def _sentence(link: Link) -> str:
    return f'{link.from_key} {link.relation} {link.to_key}'
