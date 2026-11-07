from pathlib import Path

import httpx
import pytest

from tests.jira_api import JiraApi

RESOURCES = Path(__file__).parents[1] / 'resources' / 'cli'


@pytest.fixture
def jira_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JiraApi:
    """Jira behind httpx's transport, with the CLI's config, credentials and a temporary directory to run in."""
    jira_api = JiraApi()

    def handle_request(_: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        return jira_api(request)

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', handle_request)
    monkeypatch.setenv('CAT_HERDER_CONFIG', str(RESOURCES / 'config.yaml'))
    monkeypatch.setenv('JIRA_EMAIL', 'ana@example.com')
    monkeypatch.setenv('JIRA_TOKEN', 'token')
    monkeypatch.chdir(tmp_path)
    return jira_api
