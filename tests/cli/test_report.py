import pytest

from cat_herder.cli import main


@pytest.mark.parametrize(('args', 'error'), [
    pytest.param(['web'], 'not a configured project: web', id='unknown-project'),
    pytest.param(
        ['sat', '--from', '2026-10-02', '--to', '2026-10-01'], '--from 2026-10-02 is after --to 2026-10-01', id='range'
    ),
])
def test_report_project_rejects_wrong_arguments(capsys: pytest.CaptureFixture[str], args: list[str], error: str):
    # WHEN
    exit_code = main(['report', 'project', *args])

    # THEN
    assert exit_code == 2
    assert capsys.readouterr().err == f'cat-herder report project: {error}\n'
