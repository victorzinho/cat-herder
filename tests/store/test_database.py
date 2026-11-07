import importlib
import pkgutil
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import cat_herder.store
from cat_herder.store.base import Base
from cat_herder.store.database import open_database


def test_migrations_create_the_tables_as_declared(tmp_path: Path) -> None:
    # GIVEN every table declared. A table joins Base.metadata only when the module defining its row class is
    # imported, which other tests may or may not have done, so every store module is imported here.
    for module in pkgutil.iter_modules(cat_herder.store.__path__):
        importlib.import_module(f'cat_herder.store.{module.name}')
    engine = open_database(tmp_path)

    # WHEN
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    # THEN
    assert differences == []
