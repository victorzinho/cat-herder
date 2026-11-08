import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from tests.dates import parse
from tests.factories import new_toggl_source_config

RESOURCES = Path(__file__).parent / 'resources' / 'sources' / 'toggl'
TOGGL_HOST = 'api.track.toggl.com'
# The source the resources come from.
TOGGL_CONFIG = new_toggl_source_config(workspace=1, history_from=parse('2026-01-01T00:00:00Z'))
# The Toggl projects with entries in the resources, by name.
SAT_PROJECT = 'SAT'
ADMIN_PROJECT = 'Admin'


class TogglApi:
    """Toggl Track with the projects and report rows in the resources, keeping every request it gets.

    Searches filter by project and by the inclusive dates of each entry's start, and come in pages of page_size. It
    fails to connect while unreachable, and answers searches with HTTP 402, as when out of quota, once
    searches_left reaches 0.
    """

    def __init__(self) -> None:
        self.reachable = True
        self.searches_left: int | None = None
        self.requests: list[httpx.Request] = []
        self.rows: list[dict[str, Any]] = json.loads((RESOURCES / 'time-entries.json').read_text())

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.reachable:
            raise httpx.ConnectError('Failed', request=request)
        match request.method, request.url.path:
            case 'GET', '/api/v9/workspaces/1/projects':
                projects = json.loads((RESOURCES / 'projects.json').read_text())
                return httpx.Response(200, json=projects if request.url.params['page'] == '1' else [])
            case 'POST', '/reports/api/v3/workspace/1/search/time_entries':
                return self._search(json.loads(request.content))
            case _:
                return httpx.Response(404, text='Not found')

    def searches(self) -> list[dict[str, Any]]:
        """The bodies of the searches received."""
        return [json.loads(request.content) for request in self.requests if request.method == 'POST']

    def _search(self, body: dict[str, Any]) -> httpx.Response:
        if self.searches_left is not None:
            if not self.searches_left:
                return httpx.Response(402, text='You have hit your hourly limit for API calls')
            self.searches_left -= 1
        start, end = date.fromisoformat(body['start_date']), date.fromisoformat(body['end_date'])
        found = [
            {**row, 'row_number': number}
            for number, row in enumerate(
                (
                    row for row in self.rows
                    if row['project_id'] in body['project_ids']
                    and start <= datetime.fromisoformat(row['time_entries'][0]['start']).date() <= end
                ),
                start=1,
            )
        ]
        first = body.get('first_row_number', 1)
        page = found[first - 1 : first - 1 + body['page_size']]
        has_more = first - 1 + body['page_size'] < len(found)
        headers = {'X-Next-Row-Number': str(first + body['page_size'])} if has_more else {}
        return httpx.Response(200, json=page, headers=headers)
