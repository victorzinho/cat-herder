from datetime import datetime
from typing import Any, cast

from cat_herder.domain.config import JiraSourceConfig
from cat_herder.domain.ticket import (
    Attachment,
    Change,
    Comment,
    CustomValue,
    Link,
    Sprint,
    SprintState,
    Ticket,
    TicketSummary,
)
from cat_herder.sources.errors import SourceError
from cat_herder.sources.jira.adf import adf_to_markdown
from cat_herder.sources.jira.client import JsonObject

SUMMARY_FIELDS = ('summary', 'status', 'issuetype')
TICKET_FIELDS = (
    *SUMMARY_FIELDS,
    'project',
    'created',
    'updated',
    'description',
    'labels',
    'components',
    'assignee',
    'parent',
    'issuelinks',
    'attachment',
    'timeoriginalestimate',
)

_SPRINT_STATE_BY_JIRA_STATE = {
    'future': SprintState.NOT_STARTED,
    'active': SprintState.IN_PROGRESS,
    'closed': SprintState.ENDED,
}
# History items for these fields carry no fieldId, only a name.
_FIELD_BY_NAME = {'IssueParentAssociation': 'parent', 'Link': 'links'}
_FIELD_BY_ID = {
    'summary': 'title',
    'status': 'status',
    'issuetype': 'type',
    'assignee': 'assignee',
    'labels': 'labels',
    'components': 'components',
    'description': 'description',
    'timeoriginalestimate': 'estimated_hours',
}


def ticket_fields(config: JiraSourceConfig) -> list[str]:
    """The issue fields to request: ours, plus the ones the config names."""
    configured = [config.points_field, config.sprints_field, *config.custom_fields.values()]
    return [*TICKET_FIELDS, *(field_id for field_id in configured if field_id)]


def ticket(
    config: JiraSourceConfig,
    issue: JsonObject,
    comments: list[JsonObject],
    histories: list[JsonObject],
    children: list[JsonObject],
) -> Ticket:
    """Map an issue, its comments, its changelog and its child issues, with the fields in ticket_fields."""
    fields: JsonObject = issue['fields']
    description: JsonObject | None = fields.get('description')
    assignee: JsonObject | None = fields.get('assignee')
    parent: JsonObject | None = fields.get('parent')
    estimate: int | None = fields.get('timeoriginalestimate')
    sprints: list[JsonObject] = (fields.get(config.sprints_field) or []) if config.sprints_field else []
    links: list[Link] = []
    related_summaries = [ticket_summary(config, parent)] if parent else []
    for issue_link in fields.get('issuelinks', []):
        links.append(link(issue['key'], issue_link))
        related_summaries.append(ticket_summary(config, issue_link.get('outwardIssue') or issue_link['inwardIssue']))
    return Ticket(
        source=config.slug,
        key=issue['key'],
        space=fields['project']['key'],
        title=fields['summary'],
        type=fields['issuetype']['name'],
        status=fields['status']['name'],
        created=datetime.fromisoformat(fields['created']),
        updated=datetime.fromisoformat(fields['updated']),
        description=(adf_to_markdown(description) or None) if description else None,
        labels=tuple(fields.get('labels', [])),
        components=tuple(component['name'] for component in fields.get('components', [])),
        assignee=assignee['accountId'] if assignee else None,
        points=fields.get(config.points_field) if config.points_field else None,
        estimated_hours=estimate / 3600 if estimate is not None else None,
        sprints=tuple(_sprint(config, sprint) for sprint in sprints),
        custom_fields={
            name: _custom_value(name, fields.get(field_id)) for name, field_id in config.custom_fields.items()
        },
        comments=tuple(_comment(comment) for comment in comments),
        attachments=tuple(_attachment(attachment) for attachment in fields.get('attachment', [])),
        parent=parent['key'] if parent else None,
        children=tuple(ticket_summary(config, child) for child in children),
        links=tuple(links),
        related_summaries=tuple(related_summaries),
        changes=tuple(_changes(config, histories)),
    )


def ticket_summary(config: JiraSourceConfig, issue: JsonObject) -> TicketSummary:
    """Map an issue as others mention it, with the fields in SUMMARY_FIELDS."""
    fields: JsonObject = issue['fields']
    return TicketSummary(
        source=config.slug,
        key=issue['key'],
        title=fields['summary'],
        status=fields['status']['name'],
        type=fields['issuetype']['name'],
    )


def link(key: str, issue_link: JsonObject) -> Link:
    """Map one of the issue links of the issue with that key."""
    # The outward wording reads the same from either ticket: "A blocks B".
    relation: str = issue_link['type']['outward']
    if outward := issue_link.get('outwardIssue'):
        return Link(from_key=key, relation=relation, to_key=outward['key'])
    return Link(from_key=issue_link['inwardIssue']['key'], relation=relation, to_key=key)


def _sprint(config: JiraSourceConfig, sprint: JsonObject) -> Sprint:
    return Sprint(
        source=config.slug,
        id=str(sprint['id']),
        name=sprint['name'],
        state=_SPRINT_STATE_BY_JIRA_STATE[sprint['state']],
        start=_optional_datetime(sprint.get('startDate')),
        planned_end=_optional_datetime(sprint.get('endDate')),
        actual_end=_optional_datetime(sprint.get('completeDate')),
    )


def _custom_value(name: str, value: Any) -> CustomValue:
    if value is None or isinstance(value, str | int | float) and not isinstance(value, bool):
        return value
    if isinstance(value, dict) and isinstance(option := cast(JsonObject, value).get('value'), str):
        return option
    raise SourceError(f'Custom field {name} holds {value!r}, but only single text, number or option values are carried')


def _comment(comment: JsonObject) -> Comment:
    author: JsonObject | None = comment.get('author')
    return Comment(
        author=author['accountId'] if author else None,
        created=datetime.fromisoformat(comment['created']),
        body=adf_to_markdown(comment['body']),
    )


def _attachment(attachment: JsonObject) -> Attachment:
    return Attachment(
        id=str(attachment['id']),
        filename=attachment['filename'],
        size=attachment['size'],
        created=datetime.fromisoformat(attachment['created']),
    )


def _changes(config: JiraSourceConfig, histories: list[JsonObject]) -> list[Change]:
    field_by_id = _FIELD_BY_ID | {field_id: f'custom_fields.{name}' for name, field_id in config.custom_fields.items()}
    if config.points_field:
        field_by_id[config.points_field] = 'points'
    if config.sprints_field:
        field_by_id[config.sprints_field] = 'sprints'
    changes: list[Change] = []
    for history in histories:
        author: JsonObject | None = history.get('author')
        for item in history['items']:
            field_id: str | None = item.get('fieldId')
            field = field_by_id.get(field_id) if field_id else _FIELD_BY_NAME.get(item['field'])
            if not field:
                continue
            before, after = _change_values(field, item)
            changes.append(
                Change(
                    field=field,
                    author=author['accountId'] if author else None,
                    before=before,
                    after=after,
                    date=datetime.fromisoformat(history['created']),
                )
            )
    return sorted(changes, key=lambda change: change.date)


def _change_values(field: str, item: JsonObject) -> tuple[str | None, str | None]:
    match field:
        case 'assignee':
            return item.get('from') or None, item.get('to') or None
        case 'estimated_hours':
            return _hours(item.get('from')), _hours(item.get('to'))
        case _:
            return item.get('fromString') or None, item.get('toString') or None


def _hours(seconds: str | None) -> str | None:
    return f'{int(seconds) / 3600:g}' if seconds else None


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
