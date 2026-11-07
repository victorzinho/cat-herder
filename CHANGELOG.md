# Changelog

## Unreleased

- `list` shows the tickets matching filters by project, sprint, status, assignee and update date, after syncing their projects, and answers from the local copy when Jira is unreachable.
- `sync` brings the configured spaces into the local copy, fetching only what changed since the last sync, or everything with `--force-fetch`.
- `show` reads one ticket from Jira as YAML, with `--brief`, `--changes` and `--force-fetch`, and answers from the local copy when Jira is unreachable.
