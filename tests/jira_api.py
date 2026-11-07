import json
from pathlib import Path

import httpx

from tests.factories import new_jira_source_config

RESOURCES = Path(__file__).parent / 'resources' / 'sources' / 'jira'
# The source the resources come from.
JIRA_CONFIG = new_jira_source_config(
    points_field='customfield_10035',
    sprints_field='customfield_10020',
    custom_fields={'size': 'customfield_10043', 'team': 'customfield_10044'},
)


def jira_api_with_sat(request: httpx.Request) -> httpx.Response:
    """Jira's REST API with SAT-7, its comments and children in two pages each, and its changelog.

    Searching the SAT space finds SAT-7, with one of its two comments, and its child SAT-8.
    """
    match request.method, request.url.path.removeprefix('/rest/api/3/'):
        case 'GET', 'issue/SAT-7':
            resource = 'issue.json'
        case 'GET', 'issue/SAT-7/comment':
            resource = f'comments-page-{int(request.url.params["startAt"]) + 1}.json'
        case 'GET', 'issue/SAT-7/changelog':
            resource = 'changelog.json'
        case 'POST', 'search/jql':
            body = json.loads(request.content)
            if body['jql'].startswith('project = "SAT"'):
                resource = 'space-sat.json'
            elif body['jql'].startswith('parent in ('):
                resource = 'space-sat-children.json'
            else:
                resource = f'children-page-{2 if "nextPageToken" in body else 1}.json'
        case _:
            return httpx.Response(404, json={'errorMessages': ['Issue does not exist'], 'errors': {}})
    return httpx.Response(200, json=json.loads((RESOURCES / resource).read_text()))


class JiraApi:
    """Jira with SAT-7, or failing to connect while unreachable, keeping every request it gets."""

    def __init__(self) -> None:
        self.reachable = True
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.reachable:
            raise httpx.ConnectError('Failed', request=request)
        return jira_api_with_sat(request)
