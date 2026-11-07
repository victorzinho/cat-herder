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

    def _pages(self, path: str, items_key: str, params: dict[str, str | int] | None = None) -> list[JsonObject]:
        items: list[JsonObject] = []
        while True:
            page = self._client.get(path, {**(params or {}), 'startAt': len(items), 'maxResults': PAGE_SIZE})
            items.extend(page[items_key])
            if not page[items_key] or len(items) >= page['total']:
                return items

    def _search(self, jql: str, fields: tuple[str, ...]) -> list[JsonObject]:
        issues: list[JsonObject] = []
        body: JsonObject = {'jql': jql, 'fields': list(fields), 'maxResults': PAGE_SIZE}
        while True:
            page = self._client.post('search/jql', body)
            issues.extend(page['issues'])
            if not (token := page.get('nextPageToken')):
                return issues
            body = {**body, 'nextPageToken': token}
