from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from cat_herder.store.database import open_database
from cat_herder.store.ticket_repository import TicketRow


def test_migrations_create_the_tables_as_declared(tmp_path: Path) -> None:
    # GIVEN every table declared, as importing TicketRow declares the sprints it refers to
    engine = open_database(tmp_path)

    # WHEN
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), TicketRow.metadata)

    # THEN
    assert differences == []
