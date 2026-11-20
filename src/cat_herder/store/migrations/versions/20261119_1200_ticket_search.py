"""Ticket words for full-text search, and ticket embeddings for search by meaning"""

from alembic import op

revision = '0004'
down_revision = '0003'


def upgrade() -> None:
    op.execute("""
        CREATE VIRTUAL TABLE ticket_words USING fts5(
            title, description, comments, text_hash UNINDEXED,
            tokenize = 'porter unicode61 remove_diacritics 2'
        )
    """)
    # A ticket's words go with it, as its embeddings do by their foreign key, which FTS5 tables can't have.
    op.execute("""
        CREATE TRIGGER ticket_words_of_deleted_ticket AFTER DELETE ON tickets BEGIN
            DELETE FROM ticket_words WHERE rowid = old.id;
        END
    """)
    op.execute("""
        CREATE TABLE ticket_embeddings (
            ticket_id INTEGER NOT NULL,
            model VARCHAR NOT NULL,
            position INTEGER NOT NULL,
            text_hash VARCHAR NOT NULL,
            text VARCHAR NOT NULL,
            vector BLOB NOT NULL,
            PRIMARY KEY (ticket_id, model, position),
            FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE
        )
    """)


def downgrade() -> None:
    op.execute('DROP TABLE ticket_embeddings')
    op.execute('DROP TRIGGER ticket_words_of_deleted_ticket')
    op.execute('DROP TABLE ticket_words')
