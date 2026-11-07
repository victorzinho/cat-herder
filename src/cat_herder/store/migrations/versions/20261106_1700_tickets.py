"""Tickets, sprints, comments, attachments, Changes and links"""

from alembic import op

revision = '0001'
down_revision = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tickets (
            id INTEGER NOT NULL PRIMARY KEY,
            source VARCHAR NOT NULL,
            "key" VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            type VARCHAR NOT NULL,
            parent_id INTEGER,
            fetched_at DATETIME,
            space VARCHAR,
            description VARCHAR,
            labels JSON,
            components JSON,
            assignee VARCHAR,
            points DOUBLE,
            estimated_hours DOUBLE,
            created DATETIME,
            updated DATETIME,
            custom_fields JSON,
            UNIQUE (source, "key"),
            FOREIGN KEY (parent_id) REFERENCES tickets (id) ON DELETE SET NULL
        )
    """)
    op.execute("""
        CREATE TABLE sprints (
            id INTEGER NOT NULL PRIMARY KEY,
            source VARCHAR NOT NULL,
            source_id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            state VARCHAR NOT NULL,
            start DATETIME,
            planned_end DATETIME,
            actual_end DATETIME,
            UNIQUE (source, source_id)
        )
    """)
    op.execute("""
        CREATE TABLE ticket_sprints (
            ticket_id INTEGER NOT NULL,
            sprint_id INTEGER NOT NULL,
            PRIMARY KEY (ticket_id, sprint_id),
            FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
            FOREIGN KEY (sprint_id) REFERENCES sprints (id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE comments (
            id INTEGER NOT NULL PRIMARY KEY,
            ticket_id INTEGER NOT NULL,
            author VARCHAR,
            created DATETIME NOT NULL,
            body VARCHAR NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE attachments (
            id INTEGER NOT NULL PRIMARY KEY,
            ticket_id INTEGER NOT NULL,
            source_id VARCHAR NOT NULL,
            filename VARCHAR NOT NULL,
            size INTEGER NOT NULL,
            created DATETIME NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE changes (
            id INTEGER NOT NULL PRIMARY KEY,
            ticket_id INTEGER NOT NULL,
            field VARCHAR NOT NULL,
            author VARCHAR,
            "before" VARCHAR,
            "after" VARCHAR,
            date DATETIME NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE links (
            id INTEGER NOT NULL PRIMARY KEY,
            from_id INTEGER NOT NULL,
            relation VARCHAR NOT NULL,
            to_id INTEGER NOT NULL,
            UNIQUE (from_id, relation, to_id),
            FOREIGN KEY (from_id) REFERENCES tickets (id) ON DELETE CASCADE,
            FOREIGN KEY (to_id) REFERENCES tickets (id) ON DELETE CASCADE
        )
    """)


def downgrade() -> None:
    for table in ('links', 'changes', 'attachments', 'comments', 'ticket_sprints', 'sprints', 'tickets'):
        op.execute(f'DROP TABLE {table}')
