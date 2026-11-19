from collections.abc import Mapping

import pytest

from mbench.core.folds.registry import Entry, Registry, Stamped
from mbench.core.legality.role_filters import Verdict, judge, judge_gate
from mbench.core.records.frozen import freeze
from mbench.core.records.ids import NodeId
from mbench.core.values.contested import Contested, WorldValue
from mbench.packs.spec import Linker, RoleFilter
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK, PAYMENT_CARD
from tests.testpack.values import ACTIVE, CLOSED, FROZEN, DepositKind

CHECKING = DepositKind("checking")
SAVINGS = DepositKind("savings")
CARD_LINK = "hasCorrespondingAccount"
CARD_ON_ACCOUNT = Linker(PAYMENT_CARD.name, CARD_LINK)
ACCOUNT = NodeId("acct1")
OTHER_ACCOUNT = NodeId("acct2")


def _account(kind: WorldValue = CHECKING, status: WorldValue = ACTIVE) -> Entry:
    """A deposit account holding the kind and status."""

    return Entry(
        DEPOSIT_ACCOUNT.name,
        ACCOUNT,
        {"kind": Stamped(kind, 1), "hasStatus": Stamped(status, 1)},
    )


def _card(
    id: str, status: WorldValue = ACTIVE, account: NodeId = ACCOUNT
) -> Entry:
    """A card of the given status on the account."""

    return Entry(
        PAYMENT_CARD.name,
        NodeId(id),
        {"hasStatus": Stamped(status, 1)},
        links={CARD_LINK: account},
    )


def _registry(*entries: Entry) -> Registry:
    """A registry holding exactly the entries."""

    return Registry(freeze({entry.id: entry for entry in entries}))


def _judge(
    role_filter: RoleFilter,
    entry: Entry,
    *others: Entry,
    bindings: Mapping[str, NodeId] | None = None,
) -> Verdict:
    """The filter's verdict on the entry, in a registry of it and the others."""

    registry = _registry(entry, *others)
    if bindings is None:
        return judge(role_filter, entry, registry, LOADED_PACK)

    return judge(role_filter, entry, registry, LOADED_PACK, bindings)


def test_a_filter_passes_an_entity_of_its_type() -> None:
    role_filter = RoleFilter("ACCOUNT", DEPOSIT_ACCOUNT.name)

    assert _judge(role_filter, _account()) is Verdict.PASS


def test_a_filter_fails_an_entity_of_another_type() -> None:
    role_filter = RoleFilter("CARD", PAYMENT_CARD.name)

    assert _judge(role_filter, _account()) is Verdict.FAIL


def test_a_filter_naming_no_type_passes_any_type() -> None:
    role_filter = RoleFilter("ANYTHING", None)

    assert _judge(role_filter, _account()) is Verdict.PASS
    assert _judge(role_filter, _card("card1")) is Verdict.PASS


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (CHECKING, Verdict.PASS),
        (SAVINGS, Verdict.FAIL),
        (Contested(CHECKING, SAVINGS), Verdict.UNDECIDED),
    ],
    ids=["admitted", "not admitted", "contested"],
)
def test_a_required_value_decides_the_verdict(
    kind: WorldValue, expected: Verdict
) -> None:
    role_filter = RoleFilter(
        "CHECKING", DEPOSIT_ACCOUNT.name, values={"kind": frozenset({CHECKING})}
    )

    assert _judge(role_filter, _account(kind=kind)) is expected


def test_a_required_value_the_entity_lacks_fails() -> None:
    role_filter = RoleFilter(
        "FEE", DEPOSIT_ACCOUNT.name, values={"hasMonthlyFee": frozenset()}
    )

    assert _judge(role_filter, _account()) is Verdict.FAIL


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ACTIVE, Verdict.PASS),
        (FROZEN, Verdict.PASS),
        (CLOSED, Verdict.FAIL),
        (Contested(ACTIVE, CLOSED), Verdict.UNDECIDED),
    ],
    ids=["active", "frozen", "closed", "contested"],
)
def test_live_reads_the_status(status: WorldValue, expected: Verdict) -> None:
    role_filter = RoleFilter("LIVE", DEPOSIT_ACCOUNT.name, live=True)

    assert _judge(role_filter, _account(status=status)) is expected


def test_a_filter_naming_no_type_can_ask_for_a_live_entity() -> None:
    role_filter = RoleFilter("LIVE_ANYTHING", None, live=True)

    assert _judge(role_filter, _card("card1")) is Verdict.PASS
    assert _judge(role_filter, _card("card1", CLOSED)) is Verdict.FAIL


@pytest.mark.parametrize(
    ("cards", "expected"),
    [
        ((), Verdict.PASS),
        ((_card("card1", CLOSED),), Verdict.PASS),
        ((_card("card1", account=OTHER_ACCOUNT),), Verdict.PASS),
        ((_card("card1"),), Verdict.FAIL),
        ((_card("card1", Contested(ACTIVE, CLOSED)),), Verdict.UNDECIDED),
        (
            (_card("card1", Contested(ACTIVE, CLOSED)), _card("card2")),
            Verdict.FAIL,
        ),
    ],
    ids=[
        "no card",
        "a closed card",
        "a card on another account",
        "a live card",
        "a contested card",
        "a live card beside a contested one",
    ],
)
def test_no_live_linker_reads_the_status_of_each_linker(
    cards: tuple[Entry, ...], expected: Verdict
) -> None:
    role_filter = RoleFilter(
        "NO_LIVE_CARD", DEPOSIT_ACCOUNT.name, no_live_linkers=(CARD_ON_ACCOUNT,)
    )

    assert _judge(role_filter, _account(), *cards) is expected


def test_a_failing_condition_beats_an_undecided_one() -> None:
    role_filter = RoleFilter(
        "LIVE_CHECKING",
        DEPOSIT_ACCOUNT.name,
        values={"kind": frozenset({CHECKING})},
        live=True,
    )
    account = _account(kind=Contested(CHECKING, SAVINGS), status=CLOSED)

    assert _judge(role_filter, account) is Verdict.FAIL


def test_of_passes_an_entity_linking_to_the_roles_binding() -> None:
    role_filter = RoleFilter("CARD_OF_ACCT", PAYMENT_CARD.name, of="acct")
    account = _account()
    card = _card("card1")

    on_it = _judge(role_filter, card, account, bindings={"acct": ACCOUNT})
    elsewhere = _judge(
        role_filter, card, account, bindings={"acct": OTHER_ACCOUNT}
    )

    assert on_it is Verdict.PASS
    assert elsewhere is Verdict.FAIL


def test_of_passes_whichever_link_points_at_the_binding() -> None:
    role_filter = RoleFilter("REPLACES_OLD", PAYMENT_CARD.name, of="old")
    old = _card("card1")
    # Its first link points elsewhere, so only the second can pass it.
    replacement = Entry(
        PAYMENT_CARD.name,
        NodeId("card2"),
        {"hasStatus": Stamped(ACTIVE, 1)},
        links={CARD_LINK: OTHER_ACCOUNT, "replaces": old.id},
    )

    outcome = _judge(role_filter, replacement, old, bindings={"old": old.id})

    assert outcome is Verdict.PASS


@pytest.mark.parametrize(
    "bindings", [None, {"card": NodeId("card1")}], ids=["none", "another"]
)
def test_of_a_role_not_yet_bound_is_a_caller_bug(
    bindings: Mapping[str, NodeId] | None,
) -> None:
    role_filter = RoleFilter("CARD_OF_ACCT", PAYMENT_CARD.name, of="acct")

    # An account, so the error must come before the type check fails it.
    with pytest.raises(ValueError, match="acct"):
        _judge(role_filter, _account(), bindings=bindings)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ACTIVE, Verdict.PASS),
        (CLOSED, Verdict.FAIL),
        (Contested(ACTIVE, CLOSED), Verdict.UNDECIDED),
    ],
    ids=["admitted", "not admitted", "contested"],
)
def test_a_gate_passes_fails_or_is_undecided(
    status: WorldValue, expected: Verdict
) -> None:
    gate = {"hasStatus": frozenset({ACTIVE})}

    assert judge_gate(_account(status=status), gate) is expected
