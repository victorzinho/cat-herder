from collections.abc import Callable
from typing import Any

import httpx

from cat_herder.sources.errors import SourceError, SourceUnreachable

type JsonObject = dict[str, Any]

URL = 'https://api.track.toggl.com/'
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 30


class TogglClient:
    """Toggl Track's API, raising source exceptions instead of httpx's. token is only called on the first request.

    Responses come whole, as Toggl pages through headers.
    """

    def __init__(self, token: Callable[[], str], transport: httpx.BaseTransport | None = None) -> None:
        self._token = token
        self._auth: httpx.BasicAuth | None = None
        self._http = httpx.Client(
            base_url=URL,
            headers={'Accept': 'application/json'},
            timeout=httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
            transport=transport,
        )

    def get(self, path: str, params: dict[str, str | int] | None = None) -> httpx.Response:
        return self._send(self._http.build_request('GET', path, params=params))

    def post(self, path: str, body: JsonObject) -> httpx.Response:
        return self._send(self._http.build_request('POST', path, json=body))

    def _send(self, request: httpx.Request) -> httpx.Response:
        described = f'{request.method} {request.url}'
        self._auth = self._auth or httpx.BasicAuth(self._token(), 'api_token')
        try:
            response = self._http.send(request, auth=self._auth)
        except (httpx.NetworkError, httpx.TimeoutException, httpx.ProxyError) as error:
            raise SourceUnreachable(f'{described}: {error}') from error
        except httpx.HTTPError as error:
            raise SourceError(f'{described}: {error!r}') from error
        if response.is_error:
            raise SourceError(f'{described}: HTTP {response.status_code} {response.text[:500]}')
        return response
