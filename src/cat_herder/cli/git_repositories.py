from pathlib import Path

from cat_herder.domain.config import Config


def current_git_repository(config: Config, cwd: Path) -> str | None:
    """The slug of the configured git repository cwd is in, counting a worktree as its main repository."""
    if not (root := _main_git_repository_root(cwd)):
        return None
    return next((repo.slug for repo in config.repositories if repo.path.expanduser().resolve() == root), None)


def _main_git_repository_root(cwd: Path) -> Path | None:
    # A worktree's .git is a file pointing at its git dir, whose commondir points at the main repository's .git.
    for directory in (cwd, *cwd.parents):
        git = directory / '.git'
        if git.is_dir():
            return directory.resolve()
        if git.is_file():
            git_dir = directory / git.read_text().removeprefix('gitdir:').strip()
            common_dir = git_dir / 'commondir'
            return (git_dir / common_dir.read_text().strip()).resolve().parent if common_dir.is_file() else None
    return None
