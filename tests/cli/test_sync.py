import pytest

from cat_herder.cli import main
from tests.jira_api import JiraApi
from tests.toggl_api import TogglApi


def test_syncs_the_tickets_and_time_entries_and_says_so(
    jira_api: JiraApi, toggl_api: TogglApi, capsys: pytest.CaptureFixture[str]
) -> None:
    # WHEN
    exit_code = main(['sync'])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == 'Sync done.\n'
    assert jira_api.requests
    assert toggl_api.searches()
