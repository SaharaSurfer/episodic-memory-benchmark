from collections.abc import Callable
from dataclasses import replace

import pytest

from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.records.commands import (
    Command,
    ConflictingDoubleDisclosureCommand,
    InitCommand,
)
from mbench.core.records.ids import NodeId
from mbench.core.values.contested import Contested
from mbench.packs.spec import (
    Framing,
    Gate,
    InitAction,
    MutateAction,
    RoleFilter,
)
from tests.core.world import (
    BANK_MAY_CLOSE,
    CARD_LINK,
    CARD_WRITES,
    FEE,
    World,
    agree,
    change_fee,
    contest,
    fee_contest,
    issue,
    move,
    read,
    reprice,
    status_contest,
    with_action,
    with_entity_type,
    with_framings,
    with_gate,
    with_issue_gate,
    with_role_filter,
)
from tests.testpack.pack import (
    DEPOSIT_ACCOUNT,
    LIVE_ACCOUNT,
    LOADED_PACK,
    NO_LIVE_CARD,
    PAYMENT_CARD,
)
from tests.testpack.values import (
    ACTIVE,
    CLOSED,
    FROZEN,
    INACTIVE,
    UNDER_REVIEW,
    LastFour,
)

STATUS = "hasStatus"
CONTESTED_IN = 7
LATER = CONTESTED_IN + 2
FRESH_RATE = "3.90"
OPENING_FEE = "5"
ENTITY_SEALED = Refusal(6, Reason.ENTITY_SEALED)
PAIR_SEALED = Refusal(6, Reason.PAIR_SEALED)
FILTER_FAILED = Refusal(1, Reason.ENDPOINT_FILTER_FAILED)
ACTIVE_ONLY: Gate = {STATUS: frozenset({ACTIVE})}

# Both card moves stated by a bank letter, so a card's status can be contested.
BANK_MAY_MOVE_CARDS = with_framings(
    ACTIVATE_CARD=(Framing("BANK", "letter"),),
    CLOSE_CARD=(Framing("BANK", "letter"),),
)


def _contested_case(world: World) -> NodeId:
    """A case opened in the world, its status then contested."""

    case = world.open_case()
    world.accept(status_contest(case, CONTESTED_IN, UNDER_REVIEW, CLOSED))

    return case


def _status_contested_account(world: World) -> NodeId:
    """An account opened in the world, its status then contested."""

    account = world.open()
    world.accept(status_contest(account, CONTESTED_IN, FROZEN, CLOSED))

    return account


def _status_contested_card(world: World, account: NodeId) -> NodeId:
    """A card issued on the account, its status then contested."""

    card = world.issue_card(account)
    world.accept(status_contest(card, CONTESTED_IN, ACTIVE, CLOSED))

    return card


def _second_card(
    account: NodeId, filter_name: str | None = None
) -> InitCommand:
    """A later card on the account, its anchor clear of the first card's."""

    filters = {} if filter_name is None else {CARD_LINK: filter_name}

    return replace(
        issue(account, LATER),
        writes={**CARD_WRITES, "lastFour": LastFour("7777")},
        filters=filters,
    )


def test_a_contested_case_status_is_accepted_when_both_moves_may_be() -> None:
    world = World()
    case = _contested_case(world)

    entry = world.registry.entry(case)
    assert entry is not None
    assert entry.values[STATUS].value == Contested(UNDER_REVIEW, CLOSED)


def test_a_case_status_is_not_contested_if_the_owner_states_a_move() -> None:
    world = World(with_framings(CLOSE_CASE=(Framing("CLIENT", "customer"),)))
    case = world.open_case()

    outcome = world.decide(
        status_contest(case, CONTESTED_IN, UNDER_REVIEW, CLOSED)
    )

    assert outcome == Refusal(5, Reason.NO_CONTESTABLE_FRAMING)


@pytest.mark.parametrize(
    "action", ["REVIEW_CASE", "APPROVE_CASE", "DENY_CASE", "CLOSE_CASE"]
)
def test_no_case_move_follows_a_contested_status(action: str) -> None:
    world = World()
    case = _contested_case(world)

    assert world.decide(move(case, LATER, action)) == PAIR_SEALED


@pytest.mark.parametrize(
    "make_command",
    [
        lambda account: change_fee(account, LATER, "7"),
        lambda account: agree(account, LATER, FRESH_RATE),
        lambda account: fee_contest(account, LATER),
    ],
    ids=["a write", "an agreeing pair", "a conflict"],
)
def test_a_sealed_entity_is_no_referent_for_any_event(
    make_command: Callable[[NodeId], Command],
) -> None:
    world = World(BANK_MAY_CLOSE)
    account = _status_contested_account(world)

    assert world.decide(make_command(account)) == ENTITY_SEALED


def test_a_sealed_referent_is_refused_before_an_unchanged_write() -> None:
    world = World(BANK_MAY_CLOSE)
    account = _status_contested_account(world)

    outcome = world.decide(change_fee(account, LATER, OPENING_FEE))

    assert outcome == ENTITY_SEALED


def test_a_gate_on_the_contested_status_leaves_the_refusal_to_sealing() -> None:
    world = World(
        with_gate(BANK_MAY_CLOSE, "REPRICE_DEPOSIT_ACCOUNT", ACTIVE_ONLY)
    )
    account = _status_contested_account(world)

    outcome = world.decide(reprice(account, LATER, FRESH_RATE))

    assert outcome == ENTITY_SEALED


def test_a_writers_gate_on_the_contested_status_leaves_it_to_sealing() -> None:
    world = World(with_gate(BANK_MAY_CLOSE, "CHANGE_ACCOUNT_FEE", ACTIVE_ONLY))
    account = _status_contested_account(world)

    assert world.decide(fee_contest(account, LATER)) == ENTITY_SEALED


def test_a_sealed_entity_is_no_endpoint() -> None:
    world = World(BANK_MAY_CLOSE)
    account = _status_contested_account(world)

    assert world.decide(issue(account, LATER)) == ENTITY_SEALED


def test_a_sealed_endpoint_is_refused_before_an_anchor_clash() -> None:
    world = World(BANK_MAY_CLOSE)
    account = world.open()
    world.issue_card(account)
    world.accept(status_contest(account, CONTESTED_IN, FROZEN, CLOSED))

    assert world.decide(issue(account, LATER)) == ENTITY_SEALED


def test_a_sealed_endpoint_on_a_later_link_is_refused() -> None:
    second_link = "alsoOn"
    two_accounts = replace(
        PAYMENT_CARD,
        links={
            **PAYMENT_CARD.links,
            second_link: frozenset({DEPOSIT_ACCOUNT.name}),
        },
    )
    joint = InitAction(
        "ISSUE_JOINT_CARD",
        referent_type=PAYMENT_CARD.name,
        links={CARD_LINK: {}, second_link: {}},
        fixes={STATUS: INACTIVE},
    )
    world = World(
        with_action(with_entity_type(BANK_MAY_CLOSE, two_accounts), joint)
    )
    fit = world.open()
    sealed = _status_contested_account(world)
    command = replace(
        issue(fit, LATER),
        action_type=joint.name,
        links={CARD_LINK: fit, second_link: sealed},
    )

    assert world.decide(command) == ENTITY_SEALED


def test_an_endpoint_gate_on_the_status_leaves_the_refusal_to_sealing() -> None:
    world = World(with_issue_gate(BANK_MAY_CLOSE, ACTIVE_ONLY))
    account = _status_contested_account(world)

    assert world.decide(issue(account, LATER)) == ENTITY_SEALED


def test_a_role_filter_on_the_status_leaves_the_refusal_to_sealing() -> None:
    active = RoleFilter(
        "ACTIVE_ACCOUNT", DEPOSIT_ACCOUNT.name, values=ACTIVE_ONLY
    )
    world = World(with_role_filter(BANK_MAY_CLOSE, active))
    account = _status_contested_account(world)
    command = replace(issue(account, LATER), filters={CARD_LINK: active.name})

    assert world.decide(command) == ENTITY_SEALED


def test_no_disclosure_may_be_about_a_sealed_case() -> None:
    world = World()
    case = _contested_case(world)

    assert world.decide(read(case, LATER)) == PAIR_SEALED


def test_a_filter_cannot_read_the_contested_status_of_a_linker() -> None:
    world = World(BANK_MAY_MOVE_CARDS)
    account = world.open()
    _status_contested_card(world, account)

    outcome = world.decide(_second_card(account, NO_LIVE_CARD))

    assert outcome == ENTITY_SEALED


def test_a_command_whose_filter_skips_the_linker_is_not_sealed() -> None:
    world = World(BANK_MAY_MOVE_CARDS)
    account = world.open()
    _status_contested_card(world, account)

    outcome = world.decide(_second_card(account))

    assert not isinstance(outcome, Refusal)


def test_a_live_linker_still_fails_the_filter_before_sealing() -> None:
    world = World(BANK_MAY_MOVE_CARDS)
    account = world.open()
    _status_contested_card(world, account)
    world.accept(_second_card(account))

    outcome = world.decide(
        replace(
            _second_card(account, NO_LIVE_CARD),
            session=LATER + 1,
            writes={**CARD_WRITES, "lastFour": LastFour("3141")},
        )
    )

    assert outcome == FILTER_FAILED


def test_a_linker_contested_only_elsewhere_still_fails_the_filter() -> None:
    renumber = MutateAction(
        "RENUMBER_CARD", referent_type=PAYMENT_CARD.name, relation="lastFour"
    )
    world = World(
        replace(
            with_action(LOADED_PACK, renumber),
            framings={
                **LOADED_PACK.framings,
                renumber.name: (Framing("BANK", "letter"),),
            },
        )
    )
    account = world.open()
    card = world.issue_card(account)
    world.accept(
        ConflictingDoubleDisclosureCommand(
            session=CONTESTED_IN,
            initiator="BANK",
            referent=card,
            relation="lastFour",
            a=LastFour("1111"),
            b=LastFour("2222"),
            sources=("letter", "email"),
        )
    )

    outcome = world.decide(_second_card(account, NO_LIVE_CARD))

    assert outcome == FILTER_FAILED


def test_contesting_a_relation_legality_reads_seals_the_entity() -> None:
    world = World(
        replace(
            LOADED_PACK,
            derivation_reads={DEPOSIT_ACCOUNT.name: frozenset({FEE})},
        )
    )
    account = world.open()
    world.accept(fee_contest(account, CONTESTED_IN))

    outcome = world.decide(reprice(account, LATER, FRESH_RATE))

    assert outcome == ENTITY_SEALED


def test_a_contested_rate_does_not_seal_the_account() -> None:
    world = World()
    account = world.open()
    world.accept(contest(account, CONTESTED_IN, "3.75", "3.60"))
    command = replace(issue(account, LATER), filters={CARD_LINK: LIVE_ACCOUNT})

    assert not isinstance(world.decide(command), Refusal)


def test_sealing_a_case_leaves_the_card_it_is_about_usable() -> None:
    world = World()
    card = world.issue_card(world.open())
    case = world.open_case(card)
    world.accept(status_contest(case, CONTESTED_IN, UNDER_REVIEW, CLOSED))

    outcome = world.decide(move(card, LATER, "ACTIVATE_CARD"))

    assert not isinstance(outcome, Refusal)
