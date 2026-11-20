import? 'local.just'
import '~/.config/bosun/recipes/python-uv.just'
set allow-duplicate-recipes

# Create a migration to fill in with SQL, e.g. `just migration "Add time entries"`
migration message:
    uv run --locked alembic -c src/cat_herder/store/alembic.ini revision -m "{{message}}"
