from pytest import CaptureFixture

from cat_herder.cli import main
from tests.jira_api import JiraApi


def test_comment_adds_the_comment(jira_api: JiraApi, capsys: CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['comment', 'SAT-7', 'Done'])

    # THEN
    assert (exit_code, capsys.readouterr()) == (0, ('', ''))
    paragraph = {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Done'}]}
    body = {'type': 'doc', 'version': 1, 'content': [paragraph]}
    assert jira_api.writes() == [('POST', 'issue/SAT-7/comment', {'body': body})]
