import math
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import quote

from cat_herder.domain.config import JiraSourceConfig
from cat_herder.domain.ticket import Ticket
from cat_herder.sources.errors import TicketNotFound
from cat_herder.sources.jira import mapping
from cat_herder.sources.jira.client import JiraClient, JiraNotFound, JsonObject

PAGE_SIZE = 100


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
        try:
            issue = self._client.get(f'issue/{quote(key, safe="")}', {
                'fields': ','.join(mapping.ticket_fields(self._config))
            })
        except JiraNotFound as error:
            raise TicketNotFound(f'{self._config.slug} has no ticket {key}') from error

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
