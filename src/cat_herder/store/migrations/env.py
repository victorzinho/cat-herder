from alembic import context

# The tool always passes its open connection: see cat_herder.store.database.open_database.
context.configure(connection=context.config.attributes['connection'])
with context.begin_transaction():
    context.run_migrations()
