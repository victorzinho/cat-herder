from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from time_machine import TimeMachineFixture

from cat_herder.domain.config import Config
from cat_herder.domain.sprint_snapshot import Blocked
from cat_herder.domain.ticket import Sprint, SprintState
from cat_herder.domain.time_entry import TimeEntry
from cat_herder.services.sprint_planning_service import SprintPlanningService
from cat_herder.store.sprint_repository import SprintRepository
from cat_herder.store.ticket_repository import TicketRepository
from cat_herder.store.time_entry_repository import TimeEntryRepository
from tests.dates import august, november, october, september
from tests.factories import new_sprint, new_ticket, new_time_entry, new_time_origin


def test_snapshot_lists_whoever_holds_its_tickets_until_it_ends(
    session: Session, time_machine: TimeMachineFixture, config: Config
) -> None:
    # GIVEN on November 1st, Bob holds SAT-1, with no capacity or hours in sat
    time_machine.move_to(november(1), tick=False)
    sprint = new_sprint(state=SprintState.NOT_STARTED, start=november(2), planned_end=november(16))
    TicketRepository(session).save(new_ticket(key='SAT-1', assignee='account-bob', sprints=(sprint,)), november(1))
    cut = SprintPlanningService(config, session)

    # WHEN
    planned = cut.snapshot(sprint)
    ended = cut.snapshot(replace(sprint, state=SprintState.ENDED, actual_end=november(16)))

    # THEN
    assert [person.person for person in planned.projects[0].people] == ['ana', 'bob']
    assert [person.person for person in ended.projects[0].people] == ['ana']


def test_snapshot_sets_aside_the_non_ticket_share_of_the_last_3_ended_sprints(
    session: Session, time_machine: TimeMachineFixture, config: Config, save_sprint_2: Callable[..., Sprint]
) -> None:
    # GIVEN on November 1st, ended sprints with 3 h on tickets and 1 h on none, then 2 h and 2 h, then 4 h on
    # tickets, and before them one with 10 h on none. The last to end has none of sat's hours. Ana works on sat and web.
    ended: list[tuple[str, datetime, list[tuple[float, str | None]]]] = [
        ('Sprint A', september(1), [(3, 'SAT-9'), (1, None)]),
        ('Sprint B', september(8), [(2, 'SAT-9'), (2, None)]),
        ('Sprint C', september(15), [(4, 'SAT-9')]),
        ('Old sprint', august(1), [(10, None)]),
        ('Web sprint', september(22), []),
    ]
    sprints = SprintRepository(session)
    entries: list[TimeEntry] = []
    for number, (name, start, hours) in enumerate(ended):
        sprints.save(new_sprint(
            id=name, name=name, state=SprintState.ENDED, start=start, actual_end=start + timedelta(days=5)
        ))
        entries += [
            new_time_entry(id=f'{number}-{index}', start=start, hours=each, ticket_key=key, sprint=name)
            for index, (each, key) in enumerate(hours)
        ]
    TimeEntryRepository(session).replace(new_time_origin(), august(1), october(31), entries)
    time_machine.move_to(november(1), tick=False)
    config = replace(config, default_non_ticket_percent=20)
    ana = replace(config.people[0], hours_by_project={'sat': 10, 'web': 10})
    cut = SprintPlanningService(replace(config, people=(ana, config.people[1])), session)

    # WHEN
    snapshot = cut.snapshot(save_sprint_2())

    # THEN sat sets aside 3 h of 12, web the default, and Ana half of each
    [sat, web] = snapshot.projects
    assert (sat.everyone.non_ticket_percent, web.everyone.non_ticket_percent) == (25, 20)
    assert snapshot.total.people[0].non_ticket_percent == 22.5


def test_a_planned_sprint_shows_where_the_work_wont_fit_and_where_capacity_is_spare(
    session: Session, time_machine: TimeMachineFixture, config: Config, save_sprint_2: Callable[..., Sprint]
) -> None:
    # GIVEN November 1st
    time_machine.move_to(november(1), tick=False)
    cut = SprintPlanningService(replace(config, default_non_ticket_percent=20), session)

    # WHEN
    snapshot = cut.snapshot(save_sprint_2())

    # THEN Bob has 15 h for 8 h in web, and the rest has room to spare, but Bob's 1 h in total is within the margin
    overloaded, spare = snapshot.wont_fit(margin_hours=1), snapshot.spare_capacity(margin_hours=1)
    assert [(
        workload.person, workload.project, workload.wont_fit_by
    ) for workload in overloaded] == [(None, 'web', 7), ('bob', 'web', 7),]
    assert [(
        workload.person, workload.project, workload.spare_capacity_by
    ) for workload in spare] == [(None, None, 23), (None, 'sat', 6), ('ana', None, 26), ('ana', 'sat', 10),]


def test_a_planned_sprint_shows_its_tickets_unassigned_unestimated_or_blocked(
    session: Session, time_machine: TimeMachineFixture, config: Config, save_sprint_2: Callable[..., Sprint]
) -> None:
    # GIVEN November 1st
    time_machine.move_to(november(1), tick=False)
    cut = SprintPlanningService(config, session)

    # WHEN
    snapshot = cut.snapshot(save_sprint_2())

    # THEN WEB-1 is blocked by SAT-1 in the sprint and WEB-2 outside it, while WEB-3 is done
    assert [ticket.key for ticket in snapshot.unassigned] == ['SAT-2']
    assert [ticket.key for ticket in snapshot.no_estimate] == ['SAT-3']
    assert snapshot.blocked_in_sprint == (Blocked(key='WEB-1', by=('SAT-1',)),)
    assert snapshot.blocked_outside == (Blocked(key='WEB-1', by=('WEB-2',)),)


def test_a_sprint_in_progress_shows_hours_above_the_capacity_or_the_estimate(
    session: Session, time_machine: TimeMachineFixture, config: Config
) -> None:
    # GIVEN a week into Sprint 3, Ana spent 3 h on SAT-1, estimated at 2 h, and 22 h on no ticket
    time_machine.move_to(november(9), tick=False)
    sprint = new_sprint(name='Sprint 3', state=SprintState.IN_PROGRESS, start=november(2), planned_end=november(16))
    ticket = new_ticket(key='SAT-1', status='In progress', assignee='account-ana', estimated_hours=2, sprints=(sprint,))
    TicketRepository(session).save(ticket, november(9))
    TimeEntryRepository(session).replace(new_time_origin(), november(2), november(9), [
        new_time_entry(id='1', start=november(3), hours=3, ticket_key='SAT-1'),
        new_time_entry(id='2', start=november(4), hours=22),
    ])
    cut = SprintPlanningService(config, session)

    # WHEN
    snapshot = cut.snapshot(sprint)

    # THEN her 20 h in sat are exceeded, but not her 40 h in total
    exceeded = snapshot.capacity_exceeded
    assert [(
        workload.person, workload.project, workload.hours_done, workload.capacity
    ) for workload in exceeded] == [(None, 'sat', 25, 20), ('ana', 'sat', 25, 20),]
    assert [(ticket.key, ticket.hours, ticket.estimate) for ticket in snapshot.estimate_exceeded] == [('SAT-1', 3, 2)]
