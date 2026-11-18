from dataclasses import replace
from itertools import combinations

import pytest

from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.values.protocol import Zone
from mbench.packs.spec import EntityType, LoadedPack
from tests.core.world import (
    CARD_WRITES,
    LAST_FOURS,
    World,
    issue,
    move,
    open_account,
    opening_lacking,
)
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK, PAYMENT_CARD
from tests.testpack.values import DepositKind, LastFour, ProductName

SAME_ZONE = Refusal(clause=7, reason=Reason.ANCHOR_SAME_ZONE)

# Every zoned class in the test pack is in the same zone only when equal, so
# these tests cannot tell a zone comparison from an equality one. Telling them
# apart needs a class whose same zone holds more than the value itself.


def _with_types(*entity_types: EntityType) -> LoadedPack:
    changed = {entity_type.name: entity_type for entity_type in entity_types}

    return replace(
        LOADED_PACK, entity_types={**LOADED_PACK.entity_types, **changed}
    )


def test_an_anchor_part_that_is_not_a_relation_of_the_type_is_refused() -> None:
    with pytest.raises(ValueError, match="'x'"):
        EntityType("BROKEN", relations={"kind": DepositKind}, anchor=("x",))


def test_a_nameable_type_anchored_on_a_class_without_zones_is_refused() -> None:
    with pytest.raises(ValueError, match="productName"):
        replace(DEPOSIT_ACCOUNT, anchor=("productName",))


def test_an_init_anchored_in_an_existing_ones_same_zone_is_refused() -> None:
    world = World()
    world.open()

    outcome = world.decide(open_account(2))

    assert outcome == SAME_ZONE


def test_a_closed_entity_still_holds_its_anchor() -> None:
    world = World()
    account = world.open()
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(open_account(3))

    assert outcome == SAME_ZONE


def test_an_init_anchored_in_an_existing_ones_near_zone_is_accepted() -> None:
    lookalike = LastFour("4417")
    assert lookalike.zone(LastFour(LAST_FOURS[0])) is Zone.NEAR

    world = World()
    world.open()

    outcome = world.decide(open_account(2, lastFour=lookalike))

    assert not isinstance(outcome, Refusal)


def test_two_part_anchors_differing_in_one_part_are_accepted() -> None:
    world = World()
    world.open()

    outcome = world.decide(open_account(2, kind=DepositKind("checking")))

    assert not isinstance(outcome, Refusal)


def test_a_second_card_with_the_first_cards_anchor_is_refused() -> None:
    world = World()
    account = world.open()
    world.issue_card(account)

    outcome = world.decide(issue(account, 3))

    assert outcome == SAME_ZONE


def test_an_anchor_clash_that_is_also_invalid_is_refused_as_invalid() -> None:
    world = World()
    world.open()

    outcome = world.decide(open_account(2, productName=DepositKind("savings")))

    assert outcome == Refusal(clause=3, reason=Reason.INVALID_VALUE)


def _anchored_on_product_name() -> World:
    """A world whose accounts anchor on product name alone, one opened."""

    # Only a type never named may anchor on a class without zones.
    unnamed = replace(DEPOSIT_ACCOUNT, anchor=("productName",), nameable=False)

    world = World(_with_types(unnamed))
    world.open()
    return world


def test_an_equal_anchor_without_zones_is_refused() -> None:
    world = _anchored_on_product_name()

    outcome = world.decide(open_account(2))

    assert outcome == SAME_ZONE


def test_an_unequal_anchor_without_zones_is_accepted() -> None:
    world = _anchored_on_product_name()
    product = ProductName("Goal Saver")

    outcome = world.decide(open_account(2, productName=product))

    assert not isinstance(outcome, Refusal)


def test_a_type_with_no_anchor_never_clashes() -> None:
    unanchored = replace(DEPOSIT_ACCOUNT, anchor=(), nameable=False)
    world = World(_with_types(unanchored))
    world.open()

    outcome = world.decide(open_account(2))

    assert not isinstance(outcome, Refusal)


def test_entities_of_two_types_never_clash() -> None:
    world = World(
        _with_types(
            replace(DEPOSIT_ACCOUNT, anchor=("lastFour",)),
            replace(PAYMENT_CARD, anchor=("lastFour",)),
        )
    )
    account = world.open(lastFour=CARD_WRITES["lastFour"])

    outcome = world.decide(issue(account, 2))

    assert not isinstance(outcome, Refusal)


@pytest.mark.parametrize(
    ("first_lacks", "second_lacks"),
    [(("lastFour",), ()), ((), ("lastFour",))],
    ids=["the existing entity", "the new one"],
)
def test_an_anchor_part_one_side_lacks_cannot_clash(
    first_lacks: tuple[str, ...], second_lacks: tuple[str, ...]
) -> None:
    world = World()
    world.accept(opening_lacking(1, *first_lacks))

    outcome = world.decide(opening_lacking(2, *second_lacks))

    assert not isinstance(outcome, Refusal)


def test_the_worlds_last_fours_are_pairwise_far() -> None:
    last_fours = [LastFour(payload) for payload in LAST_FOURS]

    for first, second in combinations(last_fours, 2):
        assert first.zone(second) is Zone.FAR
