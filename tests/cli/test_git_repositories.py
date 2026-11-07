from pathlib import Path

import pytest

from cat_herder.cli.git_repositories import current_git_repository
from cat_herder.domain.config import Config, Repository


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """sat is configured and has the worktree sat-worktree; 'unconfigured' is a git repo the config doesn't name."""
    worktree_git_dir = tmp_path / 'sat' / '.git' / 'worktrees' / 'sat-worktree'
    worktree_git_dir.mkdir(parents=True)
    (worktree_git_dir / 'commondir').write_text('../..\n')
    (tmp_path / 'sat' / 'src').mkdir()
    (tmp_path / 'sat-worktree').mkdir()
    (tmp_path / 'sat-worktree' / '.git').write_text(f'gitdir: {worktree_git_dir}\n')
    (tmp_path / 'unconfigured' / '.git').mkdir(parents=True)
    (tmp_path / 'elsewhere').mkdir()
    return Config(
        data_dir=tmp_path, sources=(), projects=(), repositories=(Repository(slug='sat', path=tmp_path / 'sat'),)
    )


@pytest.mark.parametrize(('cwd', 'expected'), [
        pytest.param('sat', 'sat', id='repository'),
        pytest.param('sat/src', 'sat', id='inside-repository'),
        pytest.param('sat-worktree', 'sat', id='worktree'),
        pytest.param('unconfigured', None, id='unconfigured-repository'),
        pytest.param('elsewhere', None, id='no-repository'),
])
def test_current_git_repository_finds_the_configured_one(config: Config, cwd: str, expected: str | None) -> None:
    # GIVEN cwd under the config's data_dir, where the repositories are
    directory = config.data_dir / cwd

    # WHEN
    repository = current_git_repository(config, directory)

    # THEN
    assert repository == expected
