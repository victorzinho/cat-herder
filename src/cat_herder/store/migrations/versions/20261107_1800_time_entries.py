"""Time entries, and when each time source was synced, with space_syncs renamed to ticket_space_syncs"""

from alembic import op

revision = '0003'
down_revision = '0002'


def upgrade() -> None:
    op.execute('ALTER TABLE space_syncs RENAME TO ticket_space_syncs')
    op.execute("""
        CREATE TABLE time_entries (
            source VARCHAR NOT NULL,
            source_id VARCHAR NOT NULL,
            space VARCHAR NOT NULL,
            person VARCHAR NOT NULL,
            description VARCHAR NOT NULL,
            start DATETIME NOT NULL,
            "end" DATETIME NOT NULL,
            ticket_key VARCHAR,
            sprint VARCHAR,
            flags JSON NOT NULL,
            PRIMARY KEY (source, source_id)
        )
    """)
    op.execute("""
        CREATE TABLE time_source_syncs (
            source VARCHAR NOT NULL PRIMARY KEY,
            spaces JSON NOT NULL,
            resume_from DATE NOT NULL,
            synced_at DATETIME NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute('DROP TABLE time_source_syncs')
    op.execute('DROP TABLE time_entries')
    op.execute('ALTER TABLE ticket_space_syncs RENAME TO space_syncs')
