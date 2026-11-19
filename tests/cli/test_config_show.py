from pathlib import Path

import pytest
import yaml

from cat_herder.cli import main
from cat_herder.store.config_file import CONFIG_PATH_ENV, load_config
from tests.helpers import CONFIG_EXAMPLE, config_schema, resource


@pytest.mark.parametrize('config', [
    pytest.param(resource('cli/workspace/config.yaml'), id='workspace'),
    pytest.param(CONFIG_EXAMPLE, id='docs-example'),
])
def test_without_arguments_prints_the_whole_config_loading_as_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], config: Path
) -> None:
    # GIVEN
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config))

    # WHEN
    exit_code = main(['config', 'show'])

    # THEN
    output = capsys.readouterr().out
    shown = tmp_path / 'shown.yaml'
    shown.write_text(output)
    assert exit_code == 0
    assert list(config_schema().iter_errors(yaml.safe_load(output))) == []  # pyright: ignore[reportUnknownMemberType]
    assert load_config({CONFIG_PATH_ENV: str(shown)}) == load_config({CONFIG_PATH_ENV: str(config)})


def test_without_arguments_prints_absolute_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # WHEN
    main(['config', 'show'])

    # THEN
    shown = yaml.safe_load(capsys.readouterr().out)
    assert (shown['data_dir'], shown['repositories']['website']) == (
        str(tmp_path / 'data'),
        str(tmp_path / 'music' / 'website'),
    )


@pytest.mark.parametrize(('target', 'expected'), [
    pytest.param('web', 'config-show-web.yaml', id='project'),
    pytest.param('code/sat-meteo', 'config-show-sat-meteo.yaml', id='repository-in-several-projects'),
    pytest.param('code/sat-worktree/src', 'config-show-sat.yaml', id='in-a-worktree'),
    pytest.param('code/tools', 'config-show-tools.yaml', id='repository-in-no-project'),
    pytest.param('{workspace}/music/website', 'config-show-web.yaml', id='absolute-path'),
])
def test_with_a_path_or_project_prints_its_part(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], target: str, expected: str
) -> None:
    # WHEN
    exit_code = main(['config', 'show', target.replace('{workspace}', str(tmp_path))])

    # THEN
    assert exit_code == 0
    assert capsys.readouterr().out == resource(f'cli/{expected}').read_text().replace('{workspace}', str(tmp_path))


@pytest.mark.parametrize(('target', 'error'), [
    pytest.param('code/elsewhere', 'code/elsewhere is not in a configured repository', id='outside-repositories'),
    pytest.param('nope', 'nope is neither a path nor a project', id='neither'),
])
def test_rejects_what_it_cant_resolve(capsys: pytest.CaptureFixture[str], target: str, error: str) -> None:
    # WHEN
    exit_code = main(['config', 'show', target])

    # THEN
    captured = capsys.readouterr()
    assert exit_code == 2
    assert (captured.out, captured.err) == ('', f'cat-herder config show: {error}\n')
