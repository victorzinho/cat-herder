# cat-herder

cat-herder helps a team keep track of its work when tickets and hours live in separate tools, such as Jira and Toggl.

With it, you can:

- Read a ticket along with its links, comments and the hours spent on it
- Create and edit tickets
- Review how a finished sprint went, from where each ticket ended up to the hours each person spent against their capacity
- Check whether a planned sprint fits each person's capacity, and what's unassigned, unestimated or blocked
- Follow a sprint in progress, from the hours done so far to whether the work left still fits

## Quick setup

Save this as `~/.config/cat-herder/config.yaml`, changing the values to match your own setup. It covers one Jira space, one Toggl project and one repository.

```yaml
data_dir: ~/.local/share/cat-herder

sources:
  jira:
    type: jira
    url: https://example.atlassian.net
    access: full
    fetch_window_seconds: 60
    done_statuses: [Done]
    blocking_relation: blocks
    fields: {points: customfield_10035, sprints: customfield_10020}
    credentials_env: {email: JIRA_EMAIL, token: JIRA_TOKEN}
  toggl:
    type: toggl
    workspace: 123
    access: read-only
    fetch_window_seconds: 900
    history_from: 2026-01-01
    credentials_env: {token: TOGGL_TOKEN}

repositories:
  web: /code/web

projects:
  web:
    tickets: {source: jira, space: WEB}
    time: {source: toggl, projects: [Website]}
    repositories: [web]
```

- `data_dir`: where the tool keeps its local copy of what it reads, and any attachments you download.
- `fetch_window_seconds`: how long the tool trusts that copy before asking the source again. Toggl's is longer because its API quota is small.
- `done_statuses`: which of your Jira's statuses count as done.
- `blocking_relation`: your Jira's wording for "A blocks B". Sprint reports use it to show blocked tickets.
- `fields`: where your Jira keeps points and sprints. These IDs are different in every Jira.
- `history_from`: how far back to read Toggl entries.
- `credentials_env`: the names of the environment variables holding your credentials. Set them before running the tool.

The tool won't run without a config. To keep it somewhere else, point `CAT_HERDER_CONFIG` at it.

Then run `cat-herder --help` to see everything it can do.

## Learn more

- [Model](docs/model.md): how the concepts fit together
- [Config schema](docs/config.schema.yaml): every config option
- [Ticket schema](docs/ticket.schema.yaml): the format for reading, creating and editing tickets
