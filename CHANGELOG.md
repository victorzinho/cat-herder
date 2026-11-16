# Changelog

## Unreleased

- New command `config show`: the config, or the part of it for a path or a project.
- New command `template`: a ticket YAML to fill in for `create`, or to change for `edit`, with each field's description
  and the values the source takes.

## 0.1.0

- New commands `show`, `list` and `sync`: Jira tickets through a local copy, which answers when Jira is unreachable.
- New commands `create`, `edit` and `comment`: write tickets, from YAML in the shape `show` prints.
- New command `report sprint`: a sprint's plan, progress and outcome against each person's capacity.
- New command `report project`: a project's points, hours and speed.
- Hours per ticket from Toggl.
