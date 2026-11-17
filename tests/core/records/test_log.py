import dataclasses
from collections.abc import Callable, Mapping
from decimal import Decimal

import pytest

from mbench.core.records.ids import NodeId
from mbench.core.records.log import (
    Disclosure,
    Event,
    InitEvent,
    Log,
    MutateEvent,
    SessionRow,
)
from mbench.core.values.protocol import ValueClass
from tests.testpack.values import (
    InterestRate,
    LastFour,
    MonetaryAmount,
)


def _event(session: int, new_id: str = "aaaaa") -> InitEvent:
    return InitEvent(
        session=session,
        initiator="CLIENT",
        action_type="OPEN_DEPOSIT_ACCOUNT",
        new_id=NodeId(new_id),
        writes={"lastFour": LastFour("4471")},
    )


def _disclosure(session: int) -> Disclosure:
    return Disclosure(
        session=session,
        source="customer",
        action_type="OPEN_DEPOSIT_ACCOUNT",
        initiator="CLIENT",
        entity=NodeId("aaaaa"),
        relation="lastFour",
        value=LastFour("4471"),
        node_id=NodeId("bbbbb"),
    )


def test_a_record_field_cannot_be_reassigned() -> None:
    event = _event(1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.session = 2  # type: ignore[misc]


def _opened(writes: Mapping[str, ValueClass]) -> InitEvent:
    return InitEvent(
        session=1,
        initiator="CLIENT",
        action_type="OPEN_DEPOSIT_ACCOUNT",
        new_id=NodeId("aaaaa"),
        writes=writes,
    )


def _fee_changed(writes: Mapping[str, ValueClass]) -> MutateEvent:
    return MutateEvent(
        session=2,
        initiator="BANK",
        action_type="CHANGE_ACCOUNT_FEE",
        referent=NodeId("aaaaa"),
        writes=writes,
    )


MAKE_EVENT = pytest.mark.parametrize(
    "make", [_opened, _fee_changed], ids=["init", "mutate"]
)


@MAKE_EVENT
def test_an_events_writes_cannot_be_changed_through_it(
    make: Callable[[Mapping[str, ValueClass]], Event],
) -> None:
    event = make({"hasMonthlyFee": MonetaryAmount(Decimal("5"))})

    with pytest.raises(TypeError):
        event.writes["hasMonthlyFee"] = MonetaryAmount(Decimal("0"))  # type: ignore[index]


@MAKE_EVENT
def test_an_event_keeps_its_writes_when_the_given_map_changes(
    make: Callable[[Mapping[str, ValueClass]], Event],
) -> None:
    writes: dict[str, ValueClass] = {
        "hasMonthlyFee": MonetaryAmount(Decimal("5"))
    }
    event = make(writes)

    writes["hasMonthlyFee"] = MonetaryAmount(Decimal("0"))

    assert event.writes == {"hasMonthlyFee": MonetaryAmount(Decimal("5"))}


@pytest.mark.parametrize(
    "writes",
    [
        {},
        {
            "hasMonthlyFee": MonetaryAmount(Decimal("0")),
            "hasInterestRate": InterestRate(Decimal("3.90")),
        },
    ],
    ids=["no value", "two values"],
)
def test_a_mutate_event_writes_exactly_one_value(
    writes: dict[str, ValueClass],
) -> None:
    with pytest.raises(ValueError):
        _fee_changed(writes)


def test_the_empty_log_has_no_records_and_no_sessions() -> None:
    assert Log().records == ()
    assert dict(Log().sessions) == {}


def test_appending_keeps_order_and_leaves_the_old_log_unchanged() -> None:
    first = Log().append([_event(1), _disclosure(1)])
    second = first.append([_event(2, "ccccc")])

    assert first.records == (_event(1), _disclosure(1))
    assert second.records == (_event(1), _disclosure(1), _event(2, "ccccc"))


def test_each_new_session_gets_a_row_with_no_tier_or_date_yet() -> None:
    log = Log().append([_event(1), _disclosure(1), _event(3, "ccccc")])

    assert set(log.sessions) == {1, 3}
    assert all(
        (row.index, row.tier, row.date) == (index, None, None)
        for index, row in log.sessions.items()
    )


def test_the_session_table_cannot_be_changed_through_the_log() -> None:
    log = Log().append([_event(1)])

    with pytest.raises(TypeError):
        log.sessions[2] = SessionRow(2)  # type: ignore[index]
