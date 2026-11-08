import argparse
from collections.abc import Mapping
from pathlib import Path

from cat_herder.cli.local_copy import sync_local_copy
from cat_herder.domain.config import Config
from cat_herder.store.database import database_session, open_database


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--force-fetch', action='store_true', help="re-read everything, even within the window")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace, config: Config, environ: Mapping[str, str], cwd: Path) -> int:
    """Sync the configured spaces into the local copy.

    Returns:
        The exit code.
    """
    with database_session(open_database(config.data_dir)) as session:
        sync_local_copy(config, session, environ, args.force_fetch)
    print('Sync done.')
    return 0
