from collections.abc import Callable
from typing import Any, cast

import httpx

from cat_herder.sources.errors import SourceError, SourceUnreachable

type JsonObject = dict[str, Any]

CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 30


class JiraNotFound(SourceError):
    """Jira answered 404: what was asked for doesn't exist, or can't be seen with these credentials."""


class JiraClient:
    """Jira Cloud's REST API v3, raising source exceptions instead of httpx's.

    The url is the API's base: a site such as https://example.atlassian.net for classic tokens, or
    https://api.atlassian.com/ex/jira/<cloud id> for scoped ones. credentials gives the email and token, and is only
    called on the first request.
    """

    def __init__(
        self, url: str, credentials: Callable[[], tuple[str, str]], transport: httpx.BaseTransport | None = None
    ) -> None:
        self._credentials = credentials
        self._auth: httpx.BasicAuth | None = None
        self._http = httpx.Client(
            base_url=f'{url.rstrip("/")}/rest/api/3/',
            headers={'Accept': 'application/json'},
            timeout=httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
            transport=transport,
        )

    def get(self, path: str, params: dict[str, str | int] | None = None) -> JsonObject:
        return self._send(self._http.build_request('GET', path, params=params))

    def post(self, path: str, body: JsonObject) -> JsonObject:
        return self._send(self._http.build_request('POST', path, json=body))

    def put(self, path: str, body: JsonObject) -> JsonObject:
        return self._send(self._http.build_request('PUT', path, json=body))

    def delete(self, path: str) -> JsonObject:
        return self._send(self._http.build_request('DELETE', path))

    def _send(self, request: httpx.Request) -> JsonObject:
        described = f'{request.method} {request.url}'
        self._auth = self._auth or httpx.BasicAuth(*self._credentials())
        try:
            response = self._http.send(request, auth=self._auth)
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise SourceUnreachable(f'{described}: {error}') from error
        except httpx.HTTPError as error:
            raise SourceError(f'{described}: {error!r}') from error
        if response.status_code == 404:
            raise JiraNotFound(f'{described}: HTTP 404 {_error_detail(response)}')
        if response.is_error:
            raise SourceError(f'{described}: HTTP {response.status_code} {_error_detail(response)}')
        return response.json() if response.content else {}


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:500]
    if not isinstance(body, dict):
        return response.text[:500]
    errors = cast(JsonObject, body)
    messages: list[Any] = [*errors.get('errorMessages', []), *errors.get('errors', {}).values()]
    return '; '.join(str(message) for message in messages) or response.text[:500]
