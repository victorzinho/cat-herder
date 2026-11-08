from collections.abc import Collection, Iterator
from datetime import UTC, datetime, timedelta

from cat_herder.domain.config import TogglSourceConfig
from cat_herder.domain.time_entry import TimeEntry
from cat_herder.sources.errors import SourceError
from cat_herder.sources.toggl import mapping
from cat_herder.sources.toggl.client import JsonObject, TogglClient

# Toggl's search covers at most 366 days, and reads them in the Toggl user's time zone, so a day is added on each side.
MAX_FETCH_DAYS = 364
SEARCH_PAGE_SIZE = 1000
PROJECTS_PAGE_SIZE = 200
_DAY = timedelta(days=1)


class TogglSource:
    """A Toggl Track workspace, as a TimeSource. Spaces are projects, by name, and ticket keys come from descriptions.

    Sprints aren't reported. Project IDs are looked up once, and again only when a name isn't among them.
    """

    def __init__(self, config: TogglSourceConfig, client: TogglClient) -> None:
        self._config = config
        self._client = client
        self._project_id_by_name: dict[str, int] = {}

    @property
    def slug(self) -> str:
        return self._config.slug

    @property
    def max_fetch_days(self) -> int:
        return MAX_FETCH_DAYS

    def fetch_time_entries(
        self, spaces: Collection[str], start: datetime, end: datetime, ticket_spaces: Collection[str]
    ) -> list[TimeEntry]:
        space_by_project_id = {self._project_id(space): space for space in spaces}
        body: JsonObject = {
            'project_ids': list(space_by_project_id),
            'start_date': (start.astimezone(UTC).date() - _DAY).isoformat(),
            'end_date': (end.astimezone(UTC).date() + _DAY).isoformat(),
            'page_size': SEARCH_PAGE_SIZE,
        }
        return [
            mapping.time_entry(self._config, row, entry, space_by_project_id[row['project_id']], ticket_spaces)
            for row in self._search(body)
            for entry in row['time_entries']
            if entry['stop'] and start <= datetime.fromisoformat(entry['start']) < end
        ]

    def _project_id(self, name: str) -> int:
        if name not in self._project_id_by_name:
            self._project_id_by_name = {project['name']: project['id'] for project in self._projects()}
        if name not in self._project_id_by_name:
            raise SourceError(f'{self._config.slug} has no project {name}')
        return self._project_id_by_name[name]

    def _projects(self) -> Iterator[JsonObject]:
        page = 1
        while True:
            projects: list[JsonObject] = self._client.get(
                f'api/v9/workspaces/{self._config.workspace}/projects',
                {'active': 'both', 'per_page': PROJECTS_PAGE_SIZE, 'page': page},
            ).json()
            yield from projects
            if len(projects) < PROJECTS_PAGE_SIZE:
                return
            page += 1

    def _search(self, body: JsonObject) -> Iterator[JsonObject]:
        while True:
            response = self._client.post(f'reports/api/v3/workspace/{self._config.workspace}/search/time_entries', body)
            yield from response.json()
            if not (next_row := response.headers.get('X-Next-Row-Number')):
                return
            body = {**body, 'first_row_number': int(next_row)}
