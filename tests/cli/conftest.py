from pathlib import Path

import httpx
import pytest

from tests.jira_api import JiraApi
from tests.toggl_api import TOGGL_HOST, TogglApi

RESOURCES = Path(__file__).parents[1] / 'resources' / 'cli'


@pytest.fixture
def jira_api() -> JiraApi:
    return JiraApi()


@pytest.fixture
def toggl_api() -> TogglApi:
    return TogglApi()


@pytest.fixture(autouse=True)
def cli_environment(jira_api: JiraApi, toggl_api: TogglApi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every CLI test runs against jira_api and toggl_api behind httpx's transport, with the CLI's config and
    credentials, in a temporary directory.
    """

    def handle_request(_: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        return toggl_api(request) if request.url.host == TOGGL_HOST else jira_api(request)

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', handle_request)
    # Its data_dir is relative to it.
    config = tmp_path / 'config.yaml'
    config.write_text((RESOURCES / 'config.yaml').read_text())
    monkeypatch.setenv('CAT_HERDER_CONFIG', str(config))
    monkeypatch.setenv('JIRA_EMAIL', 'ana@example.com')
    monkeypatch.setenv('JIRA_TOKEN', 'token')
    monkeypatch.setenv('TOGGL_TOKEN', 'token')
    monkeypatch.chdir(tmp_path)
