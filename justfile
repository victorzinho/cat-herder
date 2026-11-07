check:
    uv run --locked ruff check
    uv run --locked basedpyright
    uv run --locked lint-imports
    uv run --locked pytest --cov

# Create a migration to fill in with SQL, e.g. `just migration "Add time entries"`
migration message:
    uv run --locked alembic -c src/cat_herder/store/alembic.ini revision -m "{{message}}"
