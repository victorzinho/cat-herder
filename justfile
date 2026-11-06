check:
    uv run --locked ruff check
    uv run --locked basedpyright
    uv run --locked lint-imports
    uv run --locked pytest --cov
