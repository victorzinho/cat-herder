import shutil
from pathlib import Path

import httpx
import pytest
import yaml

from tests.helpers import resource
from tests.jira_api import JiraApi
from tests.toggl_api import TOGGL_HOST, TogglApi


@pytest.fixture
def jira_api() -> JiraApi:
    return JiraApi()


@pytest.fixture
def toggl_api() -> TogglApi:
    return TogglApi()


@pytest.fixture(autouse=True)
def cli_environment(jira_api: JiraApi, toggl_api: TogglApi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every CLI test runs against jira_api and toggl_api behind httpx's transport, with the CLI's credentials, in a
    copy of the sample workspace in resources/cli/workspace.
    """

    def handle_request(_: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        return toggl_api(request) if request.url.host == TOGGL_HOST else jira_api(request)

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', handle_request)
    _copy_workspace(tmp_path)
    monkeypatch.setenv('CAT_HERDER_CONFIG', str(tmp_path / 'config.yaml'))
    monkeypatch.setenv('JIRA_EMAIL', 'ana@example.com')
    monkeypatch.setenv('JIRA_TOKEN', 'token')
    monkeypatch.setenv('TOGGL_TOKEN', 'token')
    monkeypatch.chdir(tmp_path)


def _copy_workspace(directory: Path) -> None:
    # Git doesn't keep a .git inside a repository, so each repository gets one here, as git makes them.
    shutil.copytree(resource('cli/workspace'), directory, dirs_exist_ok=True)
    for repository in yaml.safe_load((directory / 'config.yaml').read_text())['repositories'].values():
        (directory / repository / '.git').mkdir()
    worktree_git_dir = directory / 'code' / 'sat' / '.git' / 'worktrees' / 'sat-worktree'
    worktree_git_dir.mkdir(parents=True)
    (worktree_git_dir / 'commondir').write_text('../..\n')
    (directory / 'code' / 'sat-worktree' / '.git').write_text(f'gitdir: {worktree_git_dir}\n')
