from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.graph import fold_trace
from mbench.core.folds.registry import Stamped
from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.records.commands import AgreeingDoubleDisclosureCommand
from mbench.core.records.ids import NodeId
from mbench.core.records.log import Disclosure, MutateEvent
from tests.core.world import (
    MISSING,
    OPENED_IN,
    OPENING_RATE,
    World,
    agree,
    disclosures_in,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import InterestRate, MonetaryAmount

RATE = "hasInterestRate"
FRESH_RATE = "3.90"
FRESH_VALUE = InterestRate(Decimal(FRESH_RATE))


def test_accepting_gives_one_mutate_and_two_disclosures_of_its_value() -> None:
    world = World()
    account = world.open()

    records = world.accept(agree(account, 2, FRESH_RATE))

    assert [type(r) for r in records] == [
        MutateEvent,
        Disclosure,
        Disclosure,
    ]
    assert records[0] == MutateEvent(
        session=2,
        initiator="BANK",
        action_type="REPRICE_DEPOSIT_ACCOUNT",
        referent=account,
        writes={RATE: FRESH_VALUE},
    )
    assert [
        (d.source, d.session, d.entity, d.relation, d.value)
        for d in disclosures_in(records)
    ] == [
        ("letter", 2, account, RATE, FRESH_VALUE),
        ("app_notification", 2, account, RATE, FRESH_VALUE),
    ]


def test_sources_of_any_authority_may_agree() -> None:
    world = World()
    account = world.open()
    command = agree(account, 2, FRESH_RATE, sources=("customer", "operator"))

    disclosures = disclosures_in(world.accept(command))

    assert [d.source for d in disclosures] == ["customer", "operator"]


def test_the_registry_holds_the_plain_value_stamped_with_the_session() -> None:
    world = World()
    account = world.open()
    world.accept(agree(account, 2, FRESH_RATE))

    entry = world.registry.entry(account)

    assert entry is not None
    assert entry.values[RATE] == Stamped(FRESH_VALUE, 2)


def test_both_disclosures_carry_the_frame_of_the_event() -> None:
    world = World()
    account = world.open()

    disclosures = disclosures_in(world.accept(agree(account, 2, FRESH_RATE)))

    assert [(d.action_type, d.initiator) for d in disclosures] == [
        ("REPRICE_DEPOSIT_ACCOUNT", "BANK"),
        ("REPRICE_DEPOSIT_ACCOUNT", "BANK"),
    ]


def test_the_two_disclosures_carry_different_node_ids() -> None:
    world = World()
    account = world.open()

    first, second = disclosures_in(world.accept(agree(account, 2, FRESH_RATE)))

    assert first.node_id != second.node_id


def test_the_graph_gains_one_value_node_from_the_first_disclosure() -> None:
    world = World()
    account = world.open()
    first, _ = disclosures_in(world.accept(agree(account, 2, FRESH_RATE)))

    (opening, written) = world.graph.update_chain((account, RATE))

    assert opening.value == InterestRate(Decimal(OPENING_RATE))
    assert (written.id, written.value) == (first.node_id, FRESH_VALUE)


def test_the_second_disclosure_adds_nothing_to_the_graph() -> None:
    world = World()
    account = world.open()
    opening = world.records
    event, first, second = world.accept(agree(account, 2, FRESH_RATE))

    once = fold_trace((*opening, event, first), LOADED_PACK)
    twice = fold_trace((*opening, event, first, second), LOADED_PACK)

    assert twice == once


@pytest.mark.parametrize(
    ("command", "refusal"),
    [
        (
            lambda _: agree(MISSING, 2, FRESH_RATE),
            Refusal(1, Reason.REFERENT_MISSING),
        ),
        (
            lambda account: agree(account, OPENED_IN, FRESH_RATE),
            Refusal(2, Reason.PAIR_ALREADY_WRITTEN),
        ),
        (
            lambda account: replace(
                agree(account, 2, FRESH_RATE),
                value=MonetaryAmount(Decimal("1")),
            ),
            Refusal(3, Reason.INVALID_VALUE),
        ),
        (
            lambda account: agree(account, 3, OPENING_RATE),
            Refusal(8, Reason.UNCHANGED_VALUE),
        ),
    ],
    ids=["clause 1", "clause 2", "clause 3", "clause 8"],
)
def test_an_agreeing_double_is_refused_like_any_other_write(
    command: Callable[[NodeId], AgreeingDoubleDisclosureCommand],
    refusal: Refusal,
) -> None:
    world = World()
    account = world.open()

    assert world.decide(command(account)) == refusal


def test_naming_a_status_action_raises() -> None:
    world = World()
    account = world.open()
    command = replace(
        agree(account, 2, FRESH_RATE), action_type="FREEZE_DEPOSIT_ACCOUNT"
    )

    with pytest.raises(TypeError, match="cannot take status action"):
        world.decide(command)


def test_a_source_the_pack_does_not_declare_raises() -> None:
    world = World()
    account = world.open()
    command = agree(account, 2, FRESH_RATE, sources=("letter", "pigeon"))

    with pytest.raises(ValueError, match="pigeon"):
        world.decide(command)


def test_one_source_named_twice_raises() -> None:
    world = World()
    account = world.open()
    command = agree(account, 2, FRESH_RATE, sources=("letter", "letter"))

    with pytest.raises(ValueError, match="two different sources"):
        world.decide(command)
