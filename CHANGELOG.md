# Changelog

## Unreleased

- `report project` gives a project's done points, its hours on tickets and the rest, and its speed, for all time or between `--from` and `--to`.
- Toggl time entries: `show` reports the ticket's `spent_hours`, and `sync` also fetches the time sources, the first time from `history_from` and then the last 30 days. Entries naming a ticket outside their project, several tickets, or a missing one are stored with a flag.
- `list` shows the tickets matching filters by project, sprint, status, assignee and update date, after syncing their projects, and answers from the local copy when Jira is unreachable.
- `sync` brings the configured spaces into the local copy, fetching only what changed since the last sync, or everything with `--force-fetch`.
- `show` reads one ticket from Jira as YAML, with `--brief`, `--changes` and `--force-fetch`, and answers from the local copy when Jira is unreachable.
