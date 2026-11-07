# Changelog

## Unreleased

- `sync` brings the configured spaces into the local copy, fetching only what changed since the last sync, or everything with `--force-fetch`.
- `show` reads one ticket from Jira as YAML, with `--brief`, `--changes` and `--force-fetch`, and answers from the local copy when Jira is unreachable.
