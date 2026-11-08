from importlib.metadata import version

import pytest

from cat_herder.cli import main


def test_version_prints_the_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    with pytest.raises(SystemExit) as exit_info:
        main(['--version'])

    # THEN
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f'cat-herder {version("cat-herder")}\n'


def test_no_command_prints_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main([])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out.startswith('usage: cat-herder')


def test_an_error_in_what_it_was_given_prints_its_message(capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    exit_code = main(['comment', 'nope:SAT-7', 'A comment'])

    # THEN
    assert (exit_code, capsys.readouterr().err) == (1, 'cat-herder: nope is not a configured ticket source\n')


def test_any_other_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    # GIVEN a bug
    def broken(*_: object) -> None:
        raise KeyError('bug')

    monkeypatch.setattr('cat_herder.cli.load_config', broken)

    # WHEN / THEN
    with pytest.raises(KeyError, match='bug'):
        main(['sync'])
