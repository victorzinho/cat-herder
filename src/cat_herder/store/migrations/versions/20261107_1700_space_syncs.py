"""When each space was last synced"""

from alembic import op

revision = '0002'
down_revision = '0001'


def upgrade() -> None:
    op.execute("""
        CREATE TABLE space_syncs (
            source VARCHAR NOT NULL,
            space VARCHAR NOT NULL,
            synced_at DATETIME NOT NULL,
            PRIMARY KEY (source, space)
        )
    """)


def downgrade() -> None:
    op.execute('DROP TABLE space_syncs')
