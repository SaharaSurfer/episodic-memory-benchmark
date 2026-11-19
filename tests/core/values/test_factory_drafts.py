from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.registry import Registry
from mbench.core.legality.predicate import Refusal
from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    ConflictingDoubleDisclosureCommand,
    InitCommand,
    MutateCommand,
)
from mbench.core.records.ids import NodeId
from mbench.core.values.factory import (
    AgreeingDraft,
    ConflictDraft,
    Factory,
    FillReason,
    FillRefusal,
)
from mbench.core.values.samplers import Choice
from mbench.packs.spec import Framing, LoadedPack, MutateAction
from tests.core.world import (
    BANK_MAY_CLOSE,
    BRANCH_PACK,
    FEE,
    MISSING,
    OPEN_BRANCH,
    OPENING_RATE,
    WRITES,
    World,
    open_branch,
    unfilled_card,
    unfilled_fee_change,
    with_action,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.samplers import CHECKING
from tests.testpack.values import (
    CLOSED,
    FROZEN,
    InterestRate,
    LastFour,
    LifecycleStatus,
    MonetaryAmount,
    ReferenceNumber,
)

SEEDS = range(20)
RATE = "hasInterestRate"
STATUS = "hasStatus"

FIRST_FOUR = LastFour("1111")
SECOND_FOUR = LastFour("2222")
FIRST_CODE = ReferenceNumber("10001")
SECOND_CODE = ReferenceNumber("10002")
FEES = {MonetaryAmount(Decimal(fee)) for fee in ("0", "10", "12", "15")}


def _fees(*amounts: str) -> list[MonetaryAmount]:
    """The monthly fees of these amounts."""

    return [MonetaryAmount(Decimal(amount)) for amount in amounts]


def _two_four_pack() -> LoadedPack:
    """The test pack, a card's last four drawn from two values only."""

    return replace(
        LOADED_PACK,
        init_samplers={
            **LOADED_PACK.init_samplers,
            ("ISSUE_CARD", "lastFour"): Choice((FIRST_FOUR, SECOND_FOUR)),
        },
    )


def _agreeing(
    referent: NodeId, action_type: str = "CHANGE_ACCOUNT_FEE"
) -> AgreeingDraft:
    """A draft in which two documents state the account's new value."""

    return AgreeingDraft(
        session=2,
        initiator="BANK",
        action_type=action_type,
        referent=referent,
        sources=("letter", "app_notification"),
    )


def _conflict(referent: NodeId, relation: str) -> ConflictDraft:
    """A draft in which two documents state different values of the pair."""

    return ConflictDraft(
        session=2,
        initiator="BANK",
        referent=referent,
        relation=relation,
        sources=("letter", "email"),
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_an_init_draw_keeps_off_its_avoid_list(seed: int) -> None:
    pack = _two_four_pack()
    world = World(pack)
    account = world.open()

    filled = Factory(seed, pack).fill(
        unfilled_card(account),
        world.registry,
        avoid={"lastFour": [FIRST_FOUR]},
    )

    assert isinstance(filled, InitCommand)
    assert filled.writes["lastFour"] == SECOND_FOUR


def test_an_init_whose_avoid_list_leaves_nothing_is_refused() -> None:
    pack = _two_four_pack()
    world = World(pack)
    account = world.open()

    outcome = Factory(0, pack).fill(
        unfilled_card(account),
        world.registry,
        avoid={"lastFour": [FIRST_FOUR, SECOND_FOUR]},
    )

    assert outcome == FillRefusal(FillReason.EXCLUSION_LIST_EMPTY)


@pytest.mark.parametrize("seed", SEEDS)
def test_an_avoid_list_reaches_only_its_own_relation(seed: int) -> None:
    pool = Choice((FIRST_CODE, SECOND_CODE))
    pack = replace(
        BRANCH_PACK,
        init_samplers={
            (OPEN_BRANCH, "code"): pool,
            (OPEN_BRANCH, "spareCode"): pool,
        },
    )

    # The two codes must differ, so the spare code can only be the one the
    # code avoids: an avoid-list reaching it too would leave it nothing.
    filled = Factory(seed, pack).fill(
        open_branch(), Registry(), avoid={"code": [FIRST_CODE]}
    )

    assert isinstance(filled, InitCommand)
    assert (filled.writes["code"], filled.writes["spareCode"]) == (
        SECOND_CODE,
        FIRST_CODE,
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_a_mutate_step_keeps_off_its_avoid_list(seed: int) -> None:
    world = World()
    account = world.open()

    filled = Factory(seed, LOADED_PACK).fill(
        unfilled_fee_change(account),
        world.registry,
        avoid={FEE: _fees("0", "12", "15")},
    )

    assert isinstance(filled, MutateCommand)
    assert filled.value == MonetaryAmount(Decimal("10"))


def test_a_mutate_whose_avoid_list_leaves_nothing_is_refused() -> None:
    world = World()
    account = world.open()

    outcome = Factory(0, LOADED_PACK).fill(
        unfilled_fee_change(account),
        world.registry,
        avoid={FEE: _fees("0", "10", "12", "15")},
    )

    assert outcome == FillRefusal(FillReason.EXCLUSION_LIST_EMPTY)


def test_an_empty_avoid_list_with_nothing_to_draw_is_nothing_left() -> None:
    only_the_current_fee = Choice((WRITES[FEE],))
    pack = replace(
        LOADED_PACK,
        step_samplers={("DEPOSIT_ACCOUNT", FEE): only_the_current_fee},
    )
    world = World(pack)
    account = world.open()

    outcome = Factory(0, pack).fill(
        unfilled_fee_change(account), world.registry, avoid={FEE: []}
    )

    assert outcome == FillRefusal(FillReason.NOTHING_LEFT_TO_DRAW)


@pytest.mark.parametrize("seed", SEEDS)
def test_an_agreeing_draft_fills_into_an_accepted_double_disclosure(
    seed: int,
) -> None:
    world = World()
    account = world.open()
    draft = _agreeing(account)

    filled = Factory(seed, LOADED_PACK).fill(draft, world.registry)

    assert isinstance(filled, AgreeingDoubleDisclosureCommand)
    assert filled.value in FEES
    assert (filled.session, filled.initiator, filled.sources) == (
        draft.session,
        draft.initiator,
        draft.sources,
    )
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("seed", SEEDS)
def test_an_agreeing_draft_keeps_off_its_avoid_list(seed: int) -> None:
    world = World()
    account = world.open()

    filled = Factory(seed, LOADED_PACK).fill(
        _agreeing(account),
        world.registry,
        avoid={FEE: _fees("0", "10", "15")},
    )

    assert isinstance(filled, AgreeingDoubleDisclosureCommand)
    assert filled.value == MonetaryAmount(Decimal("12"))


def test_an_agreeing_draft_naming_a_status_action_raises() -> None:
    world = World()
    account = world.open()

    with pytest.raises(TypeError, match="FREEZE_DEPOSIT_ACCOUNT"):
        Factory(0, LOADED_PACK).fill(
            _agreeing(account, "FREEZE_DEPOSIT_ACCOUNT"), world.registry
        )


@pytest.mark.parametrize("seed", SEEDS)
def test_a_value_conflict_is_two_different_steps_from_the_current(
    seed: int,
) -> None:
    world = World()
    account = world.open()

    filled = Factory(seed, LOADED_PACK).fill(
        _conflict(account, RATE), world.registry
    )

    assert isinstance(filled, ConflictingDoubleDisclosureCommand)
    current = InterestRate(Decimal(OPENING_RATE))
    for value in (filled.a, filled.b):
        assert isinstance(value, InterestRate)
        assert Decimal("3.75") <= value.payload <= Decimal("4.50")
        assert value != current
    assert filled.a != filled.b
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_value_conflict_keeps_both_values_off_its_avoid_list(
    seed: int,
) -> None:
    world = World()
    account = world.open()

    filled = Factory(seed, LOADED_PACK).fill(
        _conflict(account, FEE), world.registry, avoid={FEE: _fees("0", "12")}
    )

    assert isinstance(filled, ConflictingDoubleDisclosureCommand)
    assert {filled.a, filled.b} == set(_fees("10", "15"))


def test_a_conflict_with_one_value_left_is_refused() -> None:
    world = World()
    account = world.open()

    outcome = Factory(0, LOADED_PACK).fill(
        _conflict(account, FEE),
        world.registry,
        avoid={FEE: _fees("0", "10", "12")},
    )

    assert outcome == FillRefusal(FillReason.EXCLUSION_LIST_EMPTY)


def test_a_conflict_on_no_such_entity_is_refused() -> None:
    world = World()

    outcome = Factory(0, LOADED_PACK).fill(
        _conflict(MISSING, FEE), world.registry
    )

    assert outcome == FillRefusal(FillReason.NO_CURRENT_VALUE)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_status_conflict_is_two_legal_moves_from_the_current(
    seed: int,
) -> None:
    world = World(BANK_MAY_CLOSE)
    account = world.open()

    filled = Factory(seed, BANK_MAY_CLOSE).fill(
        _conflict(account, STATUS), world.registry
    )

    assert isinstance(filled, ConflictingDoubleDisclosureCommand)
    assert {filled.a, filled.b} == {FROZEN, CLOSED}
    assert not isinstance(world.decide(filled), Refusal)


# A third move from active that only the owner states, so no conflict can
# include it, and a draw of it is refused until redrawn.
SUSPEND = MutateAction(
    "SUSPEND_DEPOSIT_ACCOUNT",
    referent_type="DEPOSIT_ACCOUNT",
    relation=STATUS,
    gate={STATUS: frozenset({LifecycleStatus("active")})},
    fixes=LifecycleStatus("pending"),
)
SUSPENDING = with_action(BANK_MAY_CLOSE, SUSPEND)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_status_conflict_redraws_a_move_no_conflict_can_frame(
    seed: int,
) -> None:
    world = World(SUSPENDING)
    account = world.open()

    filled = Factory(seed, SUSPENDING, redraw_limit=100).fill(
        _conflict(account, STATUS), world.registry
    )

    assert isinstance(filled, ConflictingDoubleDisclosureCommand)
    assert {filled.a, filled.b} == {FROZEN, CLOSED}


def test_a_status_conflict_no_framing_allows_is_refused() -> None:
    # Only the client closes an account, so no pair of moves shares a framing.
    world = World()
    account = world.open()

    outcome = Factory(0, LOADED_PACK).fill(
        _conflict(account, STATUS), world.registry
    )

    assert outcome == FillRefusal(FillReason.NO_CONTESTABLE_FRAMING)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_status_conflict_skips_a_move_whose_gate_the_entity_fails(
    seed: int,
) -> None:
    # Framed so a conflict could include it, but only a checking account may
    # take it, and the world's accounts are savings.
    pack = replace(
        with_action(
            BANK_MAY_CLOSE,
            replace(
                SUSPEND, gate={**SUSPEND.gate, "kind": frozenset({CHECKING})}
            ),
        ),
        framings={
            **BANK_MAY_CLOSE.framings,
            SUSPEND.name: (Framing("BANK", "letter"),),
        },
    )
    world = World(pack)
    account = world.open()

    # No redraw, so the move must not be drawn at all.
    filled = Factory(seed, pack, redraw_limit=0).fill(
        _conflict(account, STATUS), world.registry
    )

    assert isinstance(filled, ConflictingDoubleDisclosureCommand)
    assert {filled.a, filled.b} == {FROZEN, CLOSED}


def test_a_conflict_on_a_relation_with_no_step_sampler_raises() -> None:
    world = World()
    account = world.open()

    with pytest.raises(ValueError, match="lastFour"):
        Factory(0, LOADED_PACK).fill(
            _conflict(account, "lastFour"), world.registry
        )
