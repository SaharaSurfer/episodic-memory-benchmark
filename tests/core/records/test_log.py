import dataclasses
from collections.abc import Callable, Mapping
from decimal import Decimal
from types import MappingProxyType

import pytest

from mbench.core.records.commands import ReadCommand
from mbench.core.records.ids import NodeId
from mbench.core.records.log import (
    AcceptedCommand,
    Disclosure,
    Event,
    InitEvent,
    Log,
    MutateEvent,
    Record,
    SessionRow,
)
from mbench.core.values.protocol import ValueClass
from tests.testpack.values import (
    InterestRate,
    LastFour,
    MonetaryAmount,
)

# Read-only, since every opening that names no writes shares it.
OPENING_WRITES: Mapping[str, ValueClass] = MappingProxyType(
    {"lastFour": LastFour("4471")}
)


def _opened(
    writes: Mapping[str, ValueClass] = OPENING_WRITES,
    session: int = 1,
    new_id: str = "aaaaa",
) -> InitEvent:
    return InitEvent(
        session=session,
        initiator="CLIENT",
        action_type="OPEN_DEPOSIT_ACCOUNT",
        new_id=NodeId(new_id),
        writes=writes,
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
    event = _opened()

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.session = 2  # type: ignore[misc]


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


def _accepted(session: int, *records: Record) -> AcceptedCommand:
    command = ReadCommand(
        session=session,
        initiator="CLIENT",
        source="customer",
        entity=NodeId("aaaaa"),
    )

    return AcceptedCommand(command, records)


def test_the_empty_log_has_no_commands_records_or_sessions() -> None:
    assert Log().accepted == ()
    assert Log().records == ()
    assert dict(Log().sessions) == {}


def test_appending_keeps_order_and_leaves_the_old_log_unchanged() -> None:
    later_event = _opened(session=2, new_id="ccccc")
    opened = _accepted(1, _opened(), _disclosure(1))
    later = _accepted(2, later_event)

    first = Log().append([opened])
    second = first.append([later])

    assert first.accepted == (opened,)
    assert first.records == (_opened(), _disclosure(1))
    assert second.accepted == (opened, later)
    assert second.records == (_opened(), _disclosure(1), later_event)


def test_an_accepted_command_cannot_be_given_other_records() -> None:
    accepted = _accepted(1, _opened())

    with pytest.raises(dataclasses.FrozenInstanceError):
        accepted.records = ()  # type: ignore[misc]


def test_each_new_session_gets_a_row_with_no_tier_or_date_yet() -> None:
    log = Log().append(
        [
            _accepted(1, _opened(), _disclosure(1)),
            _accepted(3, _opened(session=3)),
        ]
    )

    assert set(log.sessions) == {1, 3}
    assert all(
        (row.index, row.tier, row.date) == (index, None, None)
        for index, row in log.sessions.items()
    )


def test_a_later_append_keeps_the_earlier_session_rows() -> None:
    first = Log().append([_accepted(1, _opened())])

    second = first.append([_accepted(2, _opened(session=2, new_id="ccccc"))])

    assert set(second.sessions) == {1, 2}


def test_an_append_leaves_an_existing_session_row_as_it_is() -> None:
    row = SessionRow(1, tier="early")

    log = Log(sessions={1: row}).append([_accepted(1, _opened())])

    assert log.sessions[1] == row


def test_a_command_that_produced_no_records_adds_no_session_row() -> None:
    log = Log().append([_accepted(1)])

    assert dict(log.sessions) == {}


def test_the_session_table_cannot_be_changed_through_the_log() -> None:
    log = Log().append([_accepted(1, _opened())])

    with pytest.raises(TypeError):
        log.sessions[2] = SessionRow(2)  # type: ignore[index]
