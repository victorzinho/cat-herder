# Model

| Concept | What it is |
|---|---|
| **Source** | A connection to a ticket (Jira) or time (Toggl) system. Named with our own slug. |
| **Project** | At most one space in a ticket source and any number of time projects in a time source, plus its repositories. Named with our own slug. |
| **Repository** | A path to a git repository locally. Worktrees count as their main repo. |
| **Person** | A slug and an identity per source. |
| **Ticket** | Identified by `<source_slug>:<key>` (`jira:VIC-1`) |
| **Link** | Two existing tickets and a relation between them. |
| **Change** | One recorded change to a ticket. |
| **Attachment** | A file on a ticket. |
| **Sprint** | Identified by `<source_slug>:<sprint_id>`. People are derived, and it has no owner. |
| **Time entry** | Datetime range for a person in a project, with a description. Optionally linked to a ticket and/or sprint. |

- A `Source` can have multiple `Project`.
- A `Project` can receive tickets from at most one space in a single ticket `Source`.
- A `Project` can receive entries from any number of time projects in a single time `Source`.
- A `Project` must be related to at least one of ticket or time `Source`. There might be projects without tickets, and projects without time entries.

- A `Project` can have multiple `Repository`.
- A `Repository` can belong to multiple `Project`.

- A `Ticket` belongs to one `Project`.
- Two `Ticket` (and a relation) form a `Link`.
- A `Ticket` can have multiple `Change`.
- A `Ticket` can have multiple `Attachment`.

- A `Sprint` belongs to a `Source` (not a `Project`; a single sprint can contain tickets from multiple projects).

- A `Person` can be linked to multiple `Source`.

- A `Time entry` belongs to a `Person` and a `Project`.
- A `Time entry` might be linked (or not) to a `Sprint`.
- A `Time entry` might be linked (or not) to a `Ticket`.

## Tickets

Tickets have a closed set of fields, and only the config can add to it, as custom fields. The YAML format is in [ticket.schema.yaml](ticket.schema.yaml).

| Group | Fields |
|---|---|
| **Identity** | Source, key, stable source ID, project |
| **Content** | Title, description (markdown), type, labels, components |
| **Workflow** | Status, assignee, points, estimated hours, parent, sprints |
| **Dates** | Created, updated, fetched at |
| **Attached** | Comments (author, date, markdown body), attachments |
| **Custom** | Single-value fields named in the source's `custom_fields` |

- Status is the source's name for it, with no category and no translation: if a Jira calls it `BLK`, it's `BLK` everywhere.
- A ticket is done if its status is in its source's `done_statuses`. Its done date is the last `Change` into one of those statuses, or its creation date if there's none.
- A ticket is discarded if its status is in its source's optional `discarded_statuses`.
- A ticket is open if it's neither done nor discarded.
- Custom fields are only carried: nothing is calculated from them.

## Links

- A link is `ticket_from`, `ticket_to` and `relation_description`, and reads as a sentence: "A blocks B".
- Both ends must be tickets in the same source.
- The relation is free text, kept as the source words it.
- A source's optional `blocking_relation` names the one where the first ticket blocks the second.

## Changes

- A change is `ticket`, `field`, `person` making the change, `from`/`to` values, and `date` of change.
- Changes are append-only and cover only the fields we persist, plus links.
- Current state comes from the ticket, and is never rebuilt from Changes.
- Every ticket source must provide history.

## Attachments

- An attachment is `ticket`, source attachment ID, `filename`, `size` and `created`.
- File contents are only stored on disk, at `<data_dir>/attachments/<source>/<attachment id>/<filename>`. The path is derived, not stored.

## People and capacity

- People are global, and each has an identity per source. Someone with no mapping appears as unknown, and their hours still count.
- Capacity is per person, in hours per week, with an optional capacity per project.
- A missing capacity counts as 0, in total or for a project.
- Unallocated capacity is the total minus the sum of the per-project capacities: hours the person could still take on.
- Project capacities can add up to more than the total. This is allowed, and reports flag it.

## Sprints

- A sprint has a name, a state (not started, in progress or ended) from the source, a start, a planned end and an actual end.
- A sprint's people are whoever has capacity in one of its projects, plus whoever has hours in it (ended) or holds one of its tickets (not started or in progress).
- A sprint that hasn't ended has no actual end yet, so its window runs from its start.

## Time entries

- An entry that names a sprint counts in that sprint.
- Otherwise, hours on a ticket count in each sprint that holds or held that ticket, if the entry's date is between the sprint's start and actual end.
- Otherwise, ticketless hours count if the entry's date is between the sprint's start and actual end, and the sprint holds tickets from the entry's project.
- An entry outside every sprint's dates counts in no sprint unless it names one.
- An entry inside two overlapping sprints counts in both, which is accepted for now.
- Entries in time-only projects count in no sprint unless they name one.
- Non-ticket work is hours from entries with no ticket.
- Planning a sprint sets aside a share of each project's capacity for non-ticket work: that share of the project's hours in its ended sprints, or `default_non_ticket_percent` if it has no ended sprints or no time source.
