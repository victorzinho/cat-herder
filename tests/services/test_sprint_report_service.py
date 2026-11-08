from collections.abc import Callable
from dataclasses import replace

from sqlalchemy.orm import Session
from time_machine import TimeMachineFixture

from cat_herder.domain.config import Config
from cat_herder.domain.ticket import Sprint, SprintState
from cat_herder.domain.time_entry import Hours
from cat_herder.services.sprint_report_service import SprintOutcome, SprintReportService, TicketCount, TicketTotals
from tests.dates import november, october


def test_ended_sprint_report(session: Session, config: Config, save_sprint_1: Callable[..., Sprint]) -> None:
    # GIVEN
    cut = SprintReportService(config, session)

    # WHEN
    report = cut.ended_sprint_report(save_sprint_1())

    # THEN
    [sat, web] = report.projects
    sat_tickets = {ticket.key: ticket for ticket in sat.tickets}
    assert list(sat_tickets) == ['SAT-1', 'SAT-2', 'SAT-3', 'SAT-4', 'SAT-5']
    assert [ticket.key for ticket in web.tickets] == ['WEB-1']

    # SAT-2 added later; SAT-3 removed; SAT-4 with 4h logged before; SAT-5 without estimate
    added, removed, carried_over, unestimated = (sat_tickets[key] for key in ('SAT-2', 'SAT-3', 'SAT-4', 'SAT-5'))
    assert (added.estimate, added.reestimated_by) == (4, 4)
    assert (removed.estimate, removed.reestimated_by, removed.outcome) == (0, -2, None)
    assert carried_over.estimate == 6
    assert unestimated.estimate is None

    # SAT-5 was done before the sprint and SAT-3 removed, so they count in no outcome
    assert (sat.project, sat.everyone.capacity, sat.estimate, sat.reestimated_by) == ('sat', 20, 18, 2)
    assert sat.hours == Hours(tickets=8, others=1)
    assert sat.outcome == SprintOutcome(
        done=TicketCount(tickets=1, points=5),
        discarded=TicketCount(tickets=1, points=1),
        open=TicketCount(tickets=1, points=3),
    )
    assert [(
        person.person, person.capacity, person.hours_done
    ) for person in sat.people] == [('ana', 20, 7), ('unknown (999)', 0, 2),]
    assert (web.project, web.everyone.capacity, web.hours) == ('web', 10, None)
    assert [(person.person, person.capacity, person.hours_done) for person in web.people] == [('bob', 10, None)]

    # the total counts each person's own capacity; web has no time source, so the hours are sat's
    total = report.total
    assert (total.everyone.capacity, total.estimate, total.reestimated_by) == (60, 23, 2)
    assert total.hours == Hours(tickets=8, others=1)
    assert total.outcome == SprintOutcome(
        done=TicketCount(tickets=2, points=13),
        discarded=TicketCount(tickets=1, points=1),
        open=TicketCount(tickets=1, points=3),
    )
    assert [(
        person.person, person.capacity, person.hours_done
    ) for person in total.people] == [('ana', 40, 7), ('bob', 20, 0), ('unknown (999)', 0, 2),]


def test_planned_sprint_report(
    session: Session, time_machine: TimeMachineFixture, config: Config, save_sprint_2: Callable[..., Sprint]
) -> None:
    # GIVEN
    time_machine.move_to(november(1), tick=False)
    cut = SprintReportService(replace(config, default_non_ticket_percent=20), session)

    # WHEN
    report = cut.planned_sprint_report(save_sprint_2())

    # THEN
    [sat, web] = report.projects
    everyone = sat.everyone
    assert (everyone.capacity_left, everyone.non_ticket_percent, everyone.ticket_capacity_left) == (20, 20, 16)
    assert sat.ticket_totals == TicketTotals(num=3, points=10, estimated_hours=10, unassigned_hours=4)
    assert [(
        person.person, person.capacity, person.ticket_capacity_left, person.work_left
    ) for person in sat.people] == [('ana', 20, 16, 6)]
    assert [(
        ticket.key, ticket.assignee, ticket.points, ticket.hours_left) for ticket in sat.open_tickets
    ] == [('SAT-1', 'ana', 5, 6), ('SAT-2', None, 3, 4), ('SAT-3', 'ana', 2, None),]
    assert (web.everyone.capacity_left, web.everyone.ticket_capacity_left) == (10, 8)
    assert web.ticket_totals == TicketTotals(num=1, points=8, estimated_hours=15, unassigned_hours=0)

    # the total counts each person's own capacity
    total = report.total
    everyone = total.everyone
    assert (everyone.capacity_left, everyone.non_ticket_percent, everyone.ticket_capacity_left) == (60, 20, 48)
    assert total.ticket_totals == TicketTotals(num=4, points=18, estimated_hours=25, unassigned_hours=4)
    assert [(
        person.person, person.capacity, person.ticket_capacity_left, person.work_left
    ) for person in total.people] == [('ana', 40, 32, 6), ('bob', 20, 16, 15),]


def test_planned_sprint_report_has_no_capacity_without_dates(
    session: Session, time_machine: TimeMachineFixture, config: Config, save_sprint_2: Callable[..., Sprint]
) -> None:
    # GIVEN
    time_machine.move_to(november(1), tick=False)
    cut = SprintReportService(config, session)

    # WHEN
    report = cut.planned_sprint_report(save_sprint_2(start=None, planned_end=None))

    # THEN
    everyone, ana = report.total.everyone, report.total.people[0]
    assert (everyone.capacity_left, everyone.ticket_capacity_left) == (None, None)
    assert (ana.capacity, ana.ticket_capacity_left, ana.work_left) == (None, None, 6)
    assert (report.problems.wont_fit, report.problems.spare_capacity) == ((), ())


def test_ongoing_sprint_report(
    session: Session, time_machine: TimeMachineFixture, config: Config, save_sprint_1: Callable[..., Sprint]
) -> None:
    # GIVEN Sprint 1 halfway through, before SAT-1 is done and SAT-4 cancelled, after SAT-3 was removed
    time_machine.move_to(october(8), tick=False)
    cut = SprintReportService(replace(config, default_non_ticket_percent=20), session)
    sprint = save_sprint_1(state=SprintState.IN_PROGRESS, actual_end=None)

    # WHEN
    report = cut.ongoing_sprint_report(sprint)

    # THEN the estimates left are 8 - 6 h on SAT-1, 4 - 2 h on SAT-2, and 10 - 4 h before the sprint on SAT-4
    [sat, web] = report.projects
    assert (sat.everyone.capacity_left, sat.everyone.ticket_capacity_left) == (10, 8)
    assert sat.ticket_totals == TicketTotals(num=3, points=9, estimated_hours=10, unassigned_hours=8)
    assert [(
        person.person, person.capacity, person.ticket_capacity_left, person.work_left
    ) for person in sat.people] == [('ana', 20, 8, 2), ('unknown (999)', 0, 0, 0),]
    assert [(
        ticket.key, ticket.hours_left
    ) for ticket in sat.open_tickets] == [('SAT-1', 2), ('SAT-2', 2), ('SAT-4', 6),]
    assert (sat.hours, sat.outcome.done) == (Hours(tickets=8, others=1), TicketCount())
    assert (web.ticket_totals.num, web.outcome.done) == (0, TicketCount(tickets=1, points=8))
    assert (report.total.everyone.capacity_left, report.total.everyone.ticket_capacity_left) == (30, 24)
