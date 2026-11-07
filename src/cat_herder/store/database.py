from collections.abc import Generator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from sqlite3 import Connection as SqliteConnection
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

DATABASE_FILENAME = 'cat-herder.sqlite'


def open_database(data_dir: Path) -> Engine:
    """Open the local copy in data_dir, creating it if needed and upgrading it to the latest migration."""
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f'sqlite:///{data_dir / DATABASE_FILENAME}')
    event.listen(engine, 'connect', _enable_foreign_keys)
    alembic_config = AlembicConfig(str(files('cat_herder.store').joinpath('alembic.ini')))
    with engine.begin() as connection:
        alembic_config.attributes['connection'] = connection
        command.upgrade(alembic_config, 'head')
    return engine


@contextmanager
def database_session(engine: Engine) -> Generator[Session]:
    """Yield a session that commits on exit, or rolls back if the block raises."""
    with Session(engine) as session, session.begin():
        yield session


def _enable_foreign_keys(connection: SqliteConnection, record: Any) -> None:
    connection.execute('PRAGMA foreign_keys = ON')
