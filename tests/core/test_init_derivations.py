from dataclasses import replace

import pytest

from mbench.core.folds.graph import Edge, EdgeKind
from mbench.core.folds.registry import Entry, Registry, fold_world
from mbench.core.legality.predicate import Reason, Refusal, check
from mbench.core.records.commands import InitCommand
from mbench.core.records.ids import NodeId
from mbench.core.records.log import CONTEST, InitEvent, MutateEvent
from mbench.core.values.contested import Contested
from mbench.core.values.factory import Factory, FillReason, FillRefusal
from mbench.packs.spec import ByType, Copy, CopyLink, InitAction, LoadedPack
from tests.core.world import (
    BANK_MAY_CLOSE,
    CARD_LINK,
    CARD_WRITES,
    ISSUED_IN,
    MISSING,
    REPLACED_IN,
    REPLACEMENT_WRITES,
    REPLACES,
    World,
    disclosures_in,
    issue,
    move,
    replacement,
    status_contest,
    with_action,
    with_entity_type,
)
from tests.testpack.pack import (
    DEPOSIT_ACCOUNT,
    LOADED_PACK,
    NO_LIVE_CARD,
    PAYMENT_CARD,
    SERVICE_CASE,
)
from tests.testpack.values import CLOSED, FROZEN, CardType, LastFour

CARD_TYPE = "cardType"
DEBIT = CardType("debit")
CREDIT = CardType("credit")
CONTESTED_IN = 7
LATER = CONTESTED_IN + 2
ENTITY_SEALED = Refusal(Reason.ENTITY_SEALED)
SAME_ZONE = Refusal(Reason.ANCHOR_SAME_ZONE)


def _init_action(pack: LoadedPack, name: str) -> InitAction:
    """The named INIT ActionType of the pack."""

    action = pack.action_types[name]
    assert isinstance(action, InitAction)

    return action


def _with_derives(
    name: str, relation: str, derivation: ByType | Copy
) -> LoadedPack:
    """The test pack with the INIT deriving the relation another way."""

    action = _init_action(LOADED_PACK, name)

    return with_action(
        LOADED_PACK,
        replace(action, derives={**action.derives, relation: derivation}),
    )


# Credit is what no default gives, so a replacement holding it has read it off
# the card it replaces. The account's type sits between two others, so only
# looking it up finds credit.
CREDIT_CARDS = _with_derives(
    "ISSUE_CARD",
    CARD_TYPE,
    ByType(
        CARD_LINK,
        {
            PAYMENT_CARD.name: DEBIT,
            DEPOSIT_ACCOUNT.name: CREDIT,
            SERVICE_CASE.name: DEBIT,
        },
    ),
)


def _entry(world: World, entity: NodeId) -> Entry:
    """The registry entry of an entity the world holds."""

    entry = world.registry.entry(entity)
    assert entry is not None

    return entry


def _entry_of_accepted(world: World, command: InitCommand) -> Entry:
    """The entry of the entity the accepted command creates."""

    event, *_ = world.accept(command)
    assert isinstance(event, InitEvent)

    return _entry(world, event.new_id)


def _carded_world(
    pack: LoadedPack = LOADED_PACK,
) -> tuple[World, NodeId, NodeId]:
    """A world over the pack with an account and a card on it."""

    world = World(pack)
    account = world.open()

    return world, account, world.issue_card(account)


def _with_contested_type(world: World, card: NodeId) -> Registry:
    """The world's registry with the card's type contested."""

    # No command can contest a two-valued class off its current value, so the
    # conflict is folded in by hand.
    contested = MutateEvent(
        session=CONTESTED_IN,
        initiator="BANK",
        action_type=CONTEST,
        referent=card,
        writes={CARD_TYPE: Contested(CREDIT, DEBIT)},
    )

    return fold_world((*world.records, contested), world.pack)


def _unfilled_replacement(card: NodeId) -> InitCommand:
    """A command replacing the card, no value chosen yet."""

    return replace(replacement(card, REPLACED_IN), writes={})


def test_a_card_on_a_deposit_account_is_a_debit_card() -> None:
    world, _, card = _carded_world()

    assert _entry(world, card).values[CARD_TYPE].value == DEBIT


def test_the_type_follows_the_mapping_for_the_accounts_type() -> None:
    world, _, card = _carded_world(CREDIT_CARDS)

    assert _entry(world, card).values[CARD_TYPE].value == CREDIT


def test_a_derived_value_is_written_and_disclosed_like_any_other() -> None:
    world = World()
    account = world.open()

    event, *rest = world.accept(issue(account, ISSUED_IN))

    assert isinstance(event, InitEvent)
    assert event.writes[CARD_TYPE] == DEBIT
    (disclosure,) = [
        d for d in disclosures_in(tuple(rest)) if d.relation == CARD_TYPE
    ]
    assert disclosure.value == DEBIT
    assert world.graph.versions((event.new_id, CARD_TYPE)) == 1


def test_a_command_writing_a_derived_value_is_a_caller_bug() -> None:
    world = World()
    command = replace(
        issue(world.open(), ISSUED_IN),
        writes={**CARD_WRITES, CARD_TYPE: DEBIT},
    )

    with pytest.raises(ValueError, match=CARD_TYPE):
        world.decide(command)


def test_a_replacement_gets_the_type_of_the_card_it_replaces() -> None:
    world, _, card = _carded_world(CREDIT_CARDS)

    new_card = world.replace_card(card)

    assert _entry(world, new_card).values[CARD_TYPE].value == CREDIT


def test_a_replacement_gets_the_account_of_the_card_it_replaces() -> None:
    world, account, card = _carded_world()

    new_card = world.replace_card(card)

    assert _entry(world, new_card).links == {REPLACES: card, CARD_LINK: account}


def test_a_copied_link_is_a_structural_edge_in_the_graph() -> None:
    world, account, card = _carded_world()

    new_card = world.replace_card(card)

    structural = {
        edge for edge in world.graph.edges() if edge.kind is EdgeKind.STRUCTURAL
    }
    assert structural == {
        Edge(EdgeKind.STRUCTURAL, card, account, CARD_LINK),
        Edge(EdgeKind.STRUCTURAL, new_card, card, REPLACES),
        Edge(EdgeKind.STRUCTURAL, new_card, account, CARD_LINK),
    }


def test_a_copied_link_is_on_the_event_and_disclosed_once() -> None:
    world, account, card = _carded_world()

    event, *rest = world.accept(replacement(card, REPLACED_IN))

    assert isinstance(event, InitEvent)
    assert event.links == {REPLACES: card, CARD_LINK: account}
    assert [d.relation for d in disclosures_in(tuple(rest))].count(
        CARD_LINK
    ) == 1


def test_a_command_naming_a_copied_link_is_a_caller_bug() -> None:
    world, account, card = _carded_world()
    command = replace(
        replacement(card, REPLACED_IN),
        links={REPLACES: card, CARD_LINK: account},
    )

    with pytest.raises(ValueError, match="links"):
        world.decide(command)


def test_a_replacement_of_a_replacement_keeps_the_account_and_type() -> None:
    world, account, card = _carded_world(CREDIT_CARDS)
    second = world.replace_card(card)
    command = replace(
        replacement(second, REPLACED_IN + 1),
        writes={**REPLACEMENT_WRITES, "lastFour": LastFour("3141")},
    )

    third = _entry_of_accepted(world, command)

    assert third.links == {REPLACES: second, CARD_LINK: account}
    assert third.values[CARD_TYPE].value == CREDIT


def test_a_derivation_reads_through_the_link_it_names() -> None:
    action = _init_action(CREDIT_CARDS, "ISSUE_REPLACEMENT_CARD")
    pack = with_action(
        CREDIT_CARDS,
        replace(action, links={REPLACES: {}, CARD_LINK: {}}, copied_links={}),
    )
    world, account, card = _carded_world(pack)
    # The account comes first and holds no card type to copy.
    command = replace(
        replacement(card, REPLACED_IN),
        links={CARD_LINK: account, REPLACES: card},
    )

    assert _entry_of_accepted(world, command).values[CARD_TYPE].value == CREDIT


def test_a_replacement_counts_as_a_live_card_on_the_account() -> None:
    world, account, card = _carded_world()
    world.accept(move(card, 3, "CLOSE_CARD"))
    command = replace(
        issue(account, LATER),
        writes={**CARD_WRITES, "lastFour": LastFour("3141")},
        filters={CARD_LINK: NO_LIVE_CARD},
    )
    assert not isinstance(world.decide(command), Refusal)

    world.replace_card(card)

    assert world.decide(command) == Refusal(Reason.ENDPOINT_FILTER_FAILED)


def test_a_closed_card_can_be_replaced() -> None:
    world, account, card = _carded_world()
    world.accept(move(card, 3, "CLOSE_CARD"))

    new_card = world.replace_card(card)

    entry = _entry(world, new_card)
    assert entry.links == {REPLACES: card, CARD_LINK: account}
    assert entry.values[CARD_TYPE].value == DEBIT


def test_a_replacement_is_compared_by_its_derived_anchor() -> None:
    world, _, card = _carded_world()
    # The card's own last four, so only the copied type completes the clash.
    command = replace(
        replacement(card, REPLACED_IN),
        writes=CARD_WRITES,
    )

    assert world.decide(command) == SAME_ZONE


def test_a_derived_value_of_the_wrong_class_is_the_packs_bug() -> None:
    pack = _with_derives(
        "ISSUE_CARD",
        CARD_TYPE,
        ByType(CARD_LINK, {DEPOSIT_ACCOUNT.name: LastFour("1234")}),
    )
    world = World(pack)

    with pytest.raises(ValueError, match=CARD_TYPE):
        world.decide(issue(world.open(), ISSUED_IN))


def test_a_type_the_mapping_lacks_is_the_packs_bug() -> None:
    pack = _with_derives("ISSUE_CARD", CARD_TYPE, ByType(CARD_LINK, {}))
    world = World(pack)

    with pytest.raises(LookupError, match=CARD_TYPE):
        world.decide(issue(world.open(), ISSUED_IN))


@pytest.mark.parametrize(
    "copy",
    [Copy(REPLACES, "noSuchRelation"), Copy("noSuchLink", CARD_TYPE)],
    ids=["relation the source lacks", "via a link the init lacks"],
)
def test_copying_a_relation_with_nothing_to_copy_is_the_packs_bug(
    copy: Copy,
) -> None:
    # The pack still builds, as a `via` naming no link is the predicate's
    # to report.
    pack = _with_derives("ISSUE_REPLACEMENT_CARD", CARD_TYPE, copy)
    world, _, card = _carded_world(pack)

    with pytest.raises(LookupError, match=CARD_TYPE):
        world.decide(replacement(card, REPLACED_IN))


@pytest.mark.parametrize(
    "copy_link",
    [CopyLink(REPLACES, "noSuchLink"), CopyLink("noSuchLink", CARD_LINK)],
    ids=["link the source lacks", "via a link the init lacks"],
)
def test_copying_a_link_with_nothing_to_copy_is_the_packs_bug(
    copy_link: CopyLink,
) -> None:
    action = _init_action(LOADED_PACK, "ISSUE_REPLACEMENT_CARD")
    pack = with_action(
        LOADED_PACK, replace(action, copied_links={CARD_LINK: copy_link})
    )
    world, _, card = _carded_world(pack)

    with pytest.raises(LookupError, match=CARD_LINK):
        world.decide(replacement(card, REPLACED_IN))


def test_copy_refuses_a_card_whose_copied_value_is_contested() -> None:
    world, _, card = _carded_world()
    registry = _with_contested_type(world, card)

    outcome = check(replacement(card, LATER), registry, LOADED_PACK)

    assert outcome == ENTITY_SEALED


def test_copy_link_refuses_a_sealed_account_it_would_copy() -> None:
    world, account, card = _carded_world(BANK_MAY_CLOSE)
    world.accept(status_contest(account, CONTESTED_IN, FROZEN, CLOSED))

    assert world.decide(replacement(card, LATER)) == ENTITY_SEALED


def test_the_factory_leaves_derived_values_to_the_predicate() -> None:
    world, account, card = _carded_world()

    filled = Factory(0, LOADED_PACK).fill(
        _unfilled_replacement(card), world.registry
    )

    assert isinstance(filled, InitCommand)
    assert set(filled.writes) == {"hasStatus", "lastFour"}
    assert _entry_of_accepted(world, filled).links == {
        REPLACES: card,
        CARD_LINK: account,
    }


def test_the_factory_redraw_sees_a_derived_anchor_part() -> None:
    pack = with_entity_type(
        LOADED_PACK,
        replace(PAYMENT_CARD, anchor=(CARD_TYPE,), nameable=False),
    )
    world, _, card = _carded_world(pack)

    filled = Factory(0, pack).fill(_unfilled_replacement(card), world.registry)

    assert filled == FillRefusal(FillReason.ANCHOR_SAME_ZONE)


def test_the_factory_fills_a_replacement_of_a_missing_card() -> None:
    world = World()

    filled = Factory(0, LOADED_PACK).fill(
        _unfilled_replacement(MISSING), world.registry
    )

    assert isinstance(filled, InitCommand)
    assert world.decide(filled) == Refusal(Reason.ENDPOINT_MISSING)
