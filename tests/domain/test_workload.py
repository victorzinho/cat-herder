import pytest

from cat_herder.domain.workload import Workload, weighted_non_ticket_percent


def test_ticket_capacity_left_sets_aside_the_non_ticket_percent_of_the_capacity_left() -> None:
    # GIVEN
    cut = _workload(capacity=40, fraction_left=0.5, non_ticket_percent=25)

    # WHEN / THEN
    assert (cut.capacity_left, cut.ticket_capacity_left) == (20, 15)


def test_capacities_are_none_without_the_sprints_dates() -> None:
    # GIVEN
    cut = _workload(capacity=None, fraction_left=None, non_ticket_percent=25)

    # WHEN / THEN
    assert (cut.capacity_left, cut.ticket_capacity_left, cut.wont_fit_by) == (None, None, None)
    assert not cut.wont_fit(0)


def test_of_everyone_adds_up_the_capacities_and_weights_the_percents_by_them() -> None:
    # GIVEN
    people = [
        _workload(capacity=30, non_ticket_percent=20),
        _workload(capacity=10, non_ticket_percent=60)
    ]

    # WHEN
    cut = Workload.of_everyone(people, project=None, fraction_left=1, hours_done=None, work_left=0)

    # THEN
    assert (cut.capacity, cut.non_ticket_percent, cut.ticket_capacity_left) == (40, 30, 28)


def test_of_everyone_keeps_a_percent_they_share() -> None:
    # GIVEN no one with capacity in the project
    people = [_workload(capacity=0, non_ticket_percent=20)]

    # WHEN
    cut = Workload.of_everyone(
        people, project='sat', fraction_left=1, non_ticket_percent=20, hours_done=None, work_left=0
    )

    # THEN
    assert (cut.capacity, cut.non_ticket_percent) == (0, 20)


def test_weighted_non_ticket_percent_is_none_without_capacity() -> None:
    # GIVEN
    workloads = [_workload(capacity=0, non_ticket_percent=20)]

    # WHEN / THEN
    assert weighted_non_ticket_percent(workloads) is None


@pytest.mark.parametrize(('work_left', 'wont_fit', 'has_spare_capacity'), [
    pytest.param(13, True, False, id='over-beyond-the-margin'),
    pytest.param(12, False, False, id='over-within-the-margin'),
    pytest.param(8, False, False, id='under-within-the-margin'),
    pytest.param(7, False, True, id='under-beyond-the-margin'),
])
def test_capacity_problems_leave_out_what_is_within_the_margin(
    work_left: float, wont_fit: bool, has_spare_capacity: bool
) -> None:
    # GIVEN 10 h for tickets, and a margin of 2 h
    cut = _workload(capacity=10, non_ticket_percent=0, work_left=work_left)

    # WHEN / THEN
    assert (cut.wont_fit(2), cut.has_spare_capacity(2)) == (wont_fit, has_spare_capacity)


def _workload(
    *, capacity: float | None, fraction_left: float | None = 1, non_ticket_percent: float | None, work_left: float = 0
) -> Workload:
    return Workload(
        person='ana',
        project='sat',
        capacity=capacity,
        fraction_left=fraction_left,
        non_ticket_percent=non_ticket_percent,
        hours_done=None,
        work_left=work_left,
    )
