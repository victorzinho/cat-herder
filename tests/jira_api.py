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

    Searching the SAT space finds SAT-7, with one of its two comments, and its child SAT-8. SAT-7 takes every write:
    its size is an option and its team a text, and it can only go to Done. Creating a ticket makes SAT-11, a Task like
    SAT-7, with nothing but its title.
    """
    match request.method, request.url.path.removeprefix('/rest/api/3/'):
        case 'GET', 'issue/SAT-7/editmeta':
            resource = 'editmeta.json'
        case 'GET', 'issueLinkType':
            resource = 'issue-link-types.json'
        case 'GET', 'issue/SAT-7/transitions' | 'issue/SAT-11/transitions':
            resource = 'transitions.json'
        case ('PUT', 'issue/SAT-7') | ('POST', 'issue/SAT-7/transitions') | ('POST', 'issue/SAT-11/transitions'):
            return httpx.Response(204)
        case 'GET', 'issue/createmeta/SAT/issuetypes':
            resource = 'createmeta-issuetypes.json'
        case 'GET', 'issue/createmeta/SAT/issuetypes/10006':
            resource = 'createmeta-task.json'
        case 'POST', 'issue':
            return httpx.Response(201, json={'id': '10011', 'key': 'SAT-11'})
        case 'GET', 'issue/SAT-11':
            resource = 'issue-sat-11.json'
        case 'GET', 'issue/SAT-11/comment':
            resource = 'no-comments.json'
        case 'GET', 'issue/SAT-11/changelog':
            resource = 'no-changes.json'
        case ('POST', 'issueLink') | ('POST', 'issue/SAT-7/comment'):
            return httpx.Response(201, json={})
        case 'DELETE', path if path.startswith('issueLink/'):
            return httpx.Response(204)
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
            elif body['jql'].startswith('parent = "SAT-11"'):
                resource = 'no-issues.json'
            else:
                resource = f'children-page-{2 if "nextPageToken" in body else 1}.json'
        case _:
            return httpx.Response(404, json={'errorMessages': ['Issue does not exist'], 'errors': {}})
    return httpx.Response(200, json=json.loads((RESOURCES / resource).read_text()))


class JiraApi:
    """Jira with SAT-7, or failing to connect while unreachable, keeping every request it gets.

    A request whose method and path, as in "PUT issue/SAT-7", is in rejecting gets a 400.
    """

    def __init__(self) -> None:
        self.reachable = True
        self.rejecting: set[str] = set()
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.reachable:
            raise httpx.ConnectError('Failed', request=request)
        if f'{request.method} {request.url.path.removeprefix("/rest/api/3/")}' in self.rejecting:
            return httpx.Response(400, json={'errorMessages': ['Rejected'], 'errors': {}})
        return jira_api_with_sat(request)

    def writes(self) -> list[tuple[str, str, object]]:
        """The method, path and JSON body of every request it got that writes."""
        return [
            (request.method, request.url.path.removeprefix('/rest/api/3/'), json.loads(request.content or 'null'))
            for request in self.requests
            if request.method != 'GET' and request.url.path != '/rest/api/3/search/jql'
        ]
