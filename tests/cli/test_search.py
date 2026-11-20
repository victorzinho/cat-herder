import pytest

from cat_herder.cli import main
from cat_herder.embeddings import encoder
from cat_herder.embeddings.encoder import EncoderUnavailable
from tests.helpers import FakeEncoder


@pytest.fixture(autouse=True)
def fake_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    def load(_: object) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(encoder, 'load_encoder', load)


def test_search_prints_each_ticket_in_columns_with_its_snippet_below(capsys: pytest.CaptureFixture[str]):
    # WHEN
    exit_code = main(['search', 'retry', 'imports'])

    # THEN SAT-7's title has both words, so its snippet is the text closest to them, and the others have no text
    assert exit_code == 0
    assert capsys.readouterr().out == (
        'SAT-7   In progress  Retry failed meteo imports\n'
        '        The import fails **silently** when the provider times out.\n'
        'SAT-10  Done         Alert on failed imports\n'
        'SAT-8   To do        Add import metrics\n'
    )


def test_search_keeps_to_the_statuses_and_limit_given(capsys: pytest.CaptureFixture[str]):
    # WHEN
    exit_code = main(['search', 'imports', '--project', 'sat', '--status', 'To do', '--status', 'Done', '--limit', '1'])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == 'SAT-10  Done  Alert on failed imports\n'


def test_search_searches_by_words_only_with_a_warning_without_the_model(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    # GIVEN
    def unavailable(_: object) -> FakeEncoder:
        raise EncoderUnavailable('no network')

    monkeypatch.setattr(encoder, 'load_encoder', unavailable)

    # WHEN
    exit_code = main(['search', 'metrics'])

    # THEN
    assert exit_code == 0
    output = capsys.readouterr()
    assert output.out == 'SAT-8  To do  Add import metrics\n'
    assert output.err == 'searching by words only, as search by meaning is unavailable: no network\n'


def test_search_rejects_a_project_not_configured(capsys: pytest.CaptureFixture[str]):
    # WHEN
    exit_code = main(['search', 'imports', '--project', 'nope'])

    # THEN
    assert exit_code == 2
    assert capsys.readouterr().err == 'cat-herder search: not configured projects: nope\n'


@pytest.mark.parametrize('limit', ['0', '-1', 'ten'])
def test_search_rejects_a_limit_not_a_positive_whole_number(capsys: pytest.CaptureFixture[str], limit: str):
    # WHEN
    with pytest.raises(SystemExit) as exit_info:
        main(['search', 'imports', '--limit', limit])

    # THEN
    assert exit_info.value.code == 2
    assert f'{limit} is not a positive whole number' in capsys.readouterr().err
