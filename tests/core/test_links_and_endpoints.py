from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.graph import Edge, EdgeKind
from mbench.core.legality.predicate import (
    Reason,
    Refusal,
    refuse_untrue_disclosure,
)
from mbench.core.records.commands import InitCommand
from mbench.core.records.ids import NodeId
from mbench.core.records.log import (
    AcceptedCommand,
    Disclosure,
    InitEvent,
    Link,
)
from mbench.packs.spec import Gate, InitAction, Linker, RoleFilter
from tests.core.records.handmade import disclosure_of
from tests.core.world import (
    CARD_LINK,
    CARD_WRITES,
    CASE_LINK,
    ISSUED_IN,
    MISSING,
    REPORTED_IN,
    World,
    issue,
    move,
    report_fraud,
)
from tests.testpack.pack import (
    CARD_ELIGIBLE_ACCOUNT,
    CHECKING_ACCOUNT,
    DEPOSIT_ACCOUNT,
    LIVE_ACCOUNT,
    LOADED_PACK,
    NO_LIVE_CARD,
    PAYMENT_CARD,
    SERVICE_CASE,
)
from tests.testpack.values import (
    ACTIVE,
    CaseKind,
    DepositKind,
    LastFour,
    MonetaryAmount,
)

FILTER_FAILED = Refusal(clause=1, reason=Reason.ENDPOINT_FILTER_FAILED)


def filtered(account: NodeId, session: int, name: str) -> InitCommand:
    """A command issuing a card, its endpoint under the named filter."""

    return replace(issue(account, session), filters={CARD_LINK: name})


def second_card(account: NodeId, session: int, name: str) -> InitCommand:
    """A filtered issue whose anchor differs from the first card's."""

    writes = {**CARD_WRITES, "lastFour": LastFour("5577")}

    return replace(filtered(account, session, name), writes=writes)


def _with_endpoint_gate(gate: Gate) -> World:
    action = InitAction(
        "ISSUE_CARD", referent_type=PAYMENT_CARD.name, links={CARD_LINK: gate}
    )
    pack = replace(
        LOADED_PACK,
        action_types={**LOADED_PACK.action_types, action.name: action},
    )
    return World(pack)


def _with_filter(role_filter: RoleFilter) -> World:
    return World(
        replace(LOADED_PACK, role_filters={role_filter.name: role_filter})
    )


def test_the_init_event_carries_its_links_beside_its_values() -> None:
    world = World()
    account = world.open()

    event, *_ = world.accept(issue(account, ISSUED_IN))

    assert isinstance(event, InitEvent)
    assert event.links == {CARD_LINK: account}
    assert event.writes == CARD_WRITES


def test_an_init_discloses_its_link_by_default() -> None:
    world = World()
    account = world.open()

    event, *rest = world.accept(issue(account, ISSUED_IN))

    assert isinstance(event, InitEvent)
    (disclosure,) = [
        d for d in rest if isinstance(d, Disclosure) and d.relation == CARD_LINK
    ]
    assert disclosure == Disclosure(
        session=ISSUED_IN,
        source="operator",
        action_type="ISSUE_CARD",
        initiator="BANK",
        entity=event.new_id,
        relation=CARD_LINK,
        value=Link(account),
        node_id=disclosure.node_id,
    )


def test_a_link_is_a_structural_edge_and_not_a_value_node() -> None:
    world = World()
    account = world.open()

    card = world.issue_card(account)

    graph = world.graph
    structural = {e for e in graph.edges() if e.kind is EdgeKind.STRUCTURAL}
    assert structural == {Edge(EdgeKind.STRUCTURAL, card, account, CARD_LINK)}
    assert graph.versions((card, CARD_LINK)) == 0
    assert graph.versions((card, "lastFour")) == 1


def test_the_registry_entry_holds_the_link() -> None:
    world = World()
    account = world.open()

    card = world.issue_card(account)

    registry = world.registry
    card_entry, account_entry = registry.entry(card), registry.entry(account)
    assert card_entry is not None
    assert account_entry is not None
    assert card_entry.links == {CARD_LINK: account}
    assert CARD_LINK not in card_entry.values
    assert account_entry.links == {}


def test_later_writes_to_the_card_keep_its_link() -> None:
    world = World()
    account = world.open()
    card = world.issue_card(account)

    world.accept(move(card, 3, "ACTIVATE_CARD"))
    world.accept(move(card, 4, "LOCK_CARD"))

    entry = world.registry.entry(card)
    assert entry is not None
    assert entry.links == {CARD_LINK: account}


def test_an_endpoint_that_does_not_exist_is_refused() -> None:
    world = World()

    outcome = world.decide(issue(MISSING, ISSUED_IN))

    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_MISSING)


def test_an_endpoint_of_a_type_the_link_does_not_point_at_is_refused() -> None:
    world = World()
    card = world.issue_card(world.open())

    outcome = world.decide(issue(card, 3))

    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_WRONG_TYPE)


def test_an_endpoint_failing_its_gate_is_refused() -> None:
    world = _with_endpoint_gate({"hasStatus": frozenset({ACTIVE})})
    account = world.open()
    passing = world.decide(issue(account, 2))
    world.accept(move(account, 2, "FREEZE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(issue(account, 3))

    assert not isinstance(passing, Refusal)
    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_GATE_FAILED)


def test_a_gate_on_a_relation_the_endpoint_lacks_refuses_it() -> None:
    world = _with_endpoint_gate(
        {"hasMonthlyFee": frozenset({MonetaryAmount(Decimal("5"))})}
    )
    account = world.open_lacking("hasMonthlyFee")

    outcome = world.decide(issue(account, ISSUED_IN))

    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_GATE_FAILED)


def test_an_endpoint_failing_its_named_filter_is_refused() -> None:
    world = World()
    savings = world.open()
    checking = world.open(kind=DepositKind("checking"))

    passing = world.decide(filtered(checking, ISSUED_IN, CHECKING_ACCOUNT))
    outcome = world.decide(filtered(savings, ISSUED_IN, CHECKING_ACCOUNT))

    assert not isinstance(passing, Refusal)
    assert outcome == FILTER_FAILED


def test_an_accepted_init_keeps_its_filter_names() -> None:
    world = World()
    account = world.open(kind=DepositKind("checking"))
    command = filtered(account, ISSUED_IN, CHECKING_ACCOUNT)

    outcome = world.decide(command)

    assert isinstance(outcome, AcceptedCommand)
    assert isinstance(outcome.command, InitCommand)
    assert outcome.command.filters == {CARD_LINK: CHECKING_ACCOUNT}


def test_a_filter_of_another_type_refuses_the_endpoint() -> None:
    world = _with_filter(RoleFilter("A_CARD", PAYMENT_CARD.name))
    account = world.open()

    outcome = world.decide(filtered(account, ISSUED_IN, "A_CARD"))

    assert outcome == FILTER_FAILED


def test_a_filter_can_require_a_live_endpoint() -> None:
    world = World()
    account = world.open()
    world.accept(move(account, 2, "FREEZE_DEPOSIT_ACCOUNT"))
    frozen = world.decide(filtered(account, 3, LIVE_ACCOUNT))
    world.accept(move(account, 3, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(filtered(account, 4, LIVE_ACCOUNT))

    assert not isinstance(frozen, Refusal)
    assert outcome == FILTER_FAILED


def test_a_filter_not_asking_for_liveness_admits_a_closed_endpoint() -> None:
    world = World()
    account = world.open(kind=DepositKind("checking"))
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(filtered(account, 3, CHECKING_ACCOUNT))

    assert not isinstance(outcome, Refusal)


def test_a_filter_can_refuse_an_endpoint_with_a_live_card_on_it() -> None:
    world = World()
    account = world.open()
    bare = world.decide(filtered(account, ISSUED_IN, NO_LIVE_CARD))
    world.issue_card(account)

    outcome = world.decide(second_card(account, 3, NO_LIVE_CARD))

    assert not isinstance(bare, Refusal)
    assert outcome == FILTER_FAILED


def test_a_closed_card_does_not_count_against_its_account() -> None:
    world = World()
    account = world.open()
    card = world.issue_card(account)
    world.accept(move(card, 3, "CLOSE_CARD"))

    outcome = world.decide(second_card(account, 4, NO_LIVE_CARD))

    assert not isinstance(outcome, Refusal)


def test_a_live_card_on_another_account_does_not_count() -> None:
    world = World()
    account = world.open()
    world.issue_card(world.open())

    outcome = world.decide(second_card(account, 3, NO_LIVE_CARD))

    assert not isinstance(outcome, Refusal)


@pytest.mark.parametrize(
    "linker",
    [
        Linker(DEPOSIT_ACCOUNT.name, CARD_LINK),
        Linker(PAYMENT_CARD.name, "replaces"),
    ],
    ids=["another-type", "another-link"],
)
def test_only_the_named_type_and_link_count_against_an_endpoint(
    linker: Linker,
) -> None:
    role_filter = RoleFilter(
        "NO_LINKER", DEPOSIT_ACCOUNT.name, no_live_linkers=(linker,)
    )
    world = _with_filter(role_filter)
    account = world.open()
    world.issue_card(account)

    outcome = world.decide(second_card(account, 3, role_filter.name))

    assert not isinstance(outcome, Refusal)


def test_a_filter_holds_only_when_all_its_conditions_do() -> None:
    world = World()
    checking = DepositKind("checking")
    savings = world.open()
    closed = world.open(kind=checking)
    carded = world.open(kind=checking)
    eligible = world.open(kind=checking)
    world.issue_card(carded)
    world.accept(move(closed, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    def outcome(account: NodeId) -> AcceptedCommand | Refusal:
        command = second_card(account, 3, CARD_ELIGIBLE_ACCOUNT)
        return world.decide(command)

    assert not isinstance(outcome(eligible), Refusal)
    assert outcome(savings) == FILTER_FAILED
    assert outcome(closed) == FILTER_FAILED
    assert outcome(carded) == FILTER_FAILED


def test_a_filter_binds_only_the_endpoint_it_is_named_for() -> None:
    replaces = "replaces"
    card_type = replace(
        PAYMENT_CARD,
        links={**PAYMENT_CARD.links, replaces: frozenset({PAYMENT_CARD.name})},
    )
    action = InitAction(
        "REPLACE_CARD",
        referent_type=PAYMENT_CARD.name,
        links={CARD_LINK: {}, replaces: {}},
    )
    world = World(
        replace(
            LOADED_PACK,
            entity_types={
                **LOADED_PACK.entity_types,
                card_type.name: card_type,
            },
            action_types={**LOADED_PACK.action_types, action.name: action},
        )
    )
    account = world.open(kind=DepositKind("checking"))
    old_card = world.issue_card(account)
    command = replace(
        second_card(account, 3, CHECKING_ACCOUNT),
        action_type=action.name,
        links={CARD_LINK: account, replaces: old_card},
    )

    on_the_account = world.decide(command)
    on_the_card = world.decide(
        replace(command, filters={replaces: CHECKING_ACCOUNT})
    )

    assert not isinstance(on_the_account, Refusal)
    assert on_the_card == FILTER_FAILED


def test_an_endpoint_need_not_be_live() -> None:
    world = World()
    account = world.open()
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(issue(account, 3))

    assert not isinstance(outcome, Refusal)


def test_the_endpoint_clause_comes_before_the_value_clause() -> None:
    world = World()
    invalid = {**CARD_WRITES, "lastFour": LastFour("12")}

    outcome = world.decide(replace(issue(MISSING, ISSUED_IN), writes=invalid))

    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_MISSING)


@pytest.mark.parametrize(
    "links",
    [{}, {CARD_LINK: MISSING, "replaces": MISSING}],
    ids=["missing", "undeclared"],
)
def test_an_init_must_name_exactly_the_links_it_writes(
    links: Mapping[str, NodeId],
) -> None:
    world = World()

    with pytest.raises(ValueError, match="links"):
        world.decide(replace(issue(MISSING, ISSUED_IN), links=links))


def test_a_filter_on_a_link_the_init_does_not_write_is_a_caller_bug() -> None:
    world = World()
    command = replace(
        issue(MISSING, ISSUED_IN), filters={"replaces": CHECKING_ACCOUNT}
    )

    with pytest.raises(ValueError, match="filter"):
        world.decide(command)


def test_a_filter_the_pack_does_not_hold_is_a_caller_bug() -> None:
    world = World()

    # The endpoint is missing too: the name is checked before any clause.
    with pytest.raises(ValueError, match="filter"):
        world.decide(filtered(MISSING, ISSUED_IN, "NO_SUCH_FILTER"))


def test_a_link_disclosure_is_true_only_of_the_linked_target() -> None:
    world = World()
    account = world.open()
    other = world.open()
    card = world.issue_card(account)
    registry = world.registry

    def stating(entity: NodeId, target: NodeId) -> Refusal | None:
        disclosure = disclosure_of(
            entity, CARD_LINK, Link(target), action_type="ISSUE_CARD"
        )
        return refuse_untrue_disclosure(disclosure, registry)

    untrue = Refusal(clause=4, reason=Reason.UNTRUE_DISCLOSURE)
    assert stating(card, account) is None
    assert stating(card, other) == untrue
    assert stating(account, other) == untrue


def test_a_card_request_opens_a_case_about_an_account() -> None:
    world = World()
    account = world.open()
    command = replace(
        report_fraud(account, REPORTED_IN, kind=CaseKind("card_request")),
        action_type="REQUEST_CARD",
    )

    event, *_ = world.accept(command)

    assert isinstance(event, InitEvent)
    entry = world.registry.entry(event.new_id)
    assert entry is not None
    assert entry.type == SERVICE_CASE.name
    assert entry.links[CASE_LINK] == account
