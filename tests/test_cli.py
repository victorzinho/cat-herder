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
