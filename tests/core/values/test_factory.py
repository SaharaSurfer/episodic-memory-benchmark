from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.registry import Registry
from mbench.core.legality.predicate import Refusal
from mbench.core.records.commands import InitCommand, MutateCommand
from mbench.core.records.ids import NodeId
from mbench.core.values.factory import Factory, FillReason, FillRefusal
from mbench.core.values.protocol import ValueClass
from mbench.core.values.samplers import ByValue, Choice
from mbench.packs.spec import MutateAction
from tests.core.records.handmade import OPEN_ACCOUNT
from tests.core.world import (
    FEE,
    MISSING,
    OPENED_IN,
    OPENING_RATE,
    REPORTED_IN,
    WRITES,
    World,
    change_fee,
    contest,
    created_id,
    fee_contest,
    issue,
    move,
    report_fraud,
    reprice,
    request_card,
    with_action,
)
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK
from tests.testpack.samplers import ANY_LAST_FOUR, CHECKING, SAVINGS
from tests.testpack.values import (
    ACTIVE,
    CHECKING_PRODUCTS,
    INACTIVE,
    OPEN,
    SAVINGS_PRODUCTS,
    CaseKind,
    InterestRate,
    MonetaryAmount,
    ProductName,
)

SEEDS = range(40)


def unfilled_opening(session: int = OPENED_IN) -> InitCommand:
    """A command opening an account, no value of it chosen yet."""

    return InitCommand(
        session=session,
        initiator="CLIENT",
        action_type=OPEN_ACCOUNT,
        source="customer",
        writes={},
    )


def filled_opening(factory: Factory, session: int = OPENED_IN) -> InitCommand:
    """The factory's filling of an opening, on an empty registry."""

    filled = factory.fill(unfilled_opening(session), Registry())
    assert isinstance(filled, InitCommand)

    return filled


def unfilled_reprice(account: NodeId, session: int = 2) -> MutateCommand:
    """A command repricing the account, the new rate not chosen yet."""

    return replace(reprice(account, session, "0"), value=None)


def unfilled_fee_change(account: NodeId, session: int = 2) -> MutateCommand:
    """A command changing the account's fee, the new fee not chosen yet."""

    return replace(change_fee(account, session, "0"), value=None)


def _filled_mutate(
    factory: Factory, command: MutateCommand, registry: Registry
) -> MutateCommand:
    """The factory's filling of a MUTATE it is expected to fill."""

    filled = factory.fill(command, registry)
    assert isinstance(filled, MutateCommand)

    return filled


def test_an_opening_comes_back_with_every_relation_set() -> None:
    filled = filled_opening(Factory(0, LOADED_PACK))

    assert set(filled.writes) == set(DEPOSIT_ACCOUNT.relations)


def test_filling_keeps_everything_but_the_writes() -> None:
    filled = filled_opening(Factory(0, LOADED_PACK))

    assert replace(filled, writes={}) == unfilled_opening()


def test_an_opening_starts_in_the_status_the_init_fixes() -> None:
    writes = filled_opening(Factory(0, LOADED_PACK)).writes

    assert writes["hasStatus"] == ACTIVE


def test_a_product_name_comes_from_the_list_of_the_kind_drawn() -> None:
    allowed: dict[ValueClass, set[ProductName]] = {
        CHECKING: set(map(ProductName, CHECKING_PRODUCTS)),
        SAVINGS: set(map(ProductName, SAVINGS_PRODUCTS)),
    }
    kinds = set()

    for seed in SEEDS:
        writes = filled_opening(Factory(seed, LOADED_PACK)).writes
        kinds.add(writes["kind"])
        assert writes["productName"] in allowed[writes["kind"]]

    # Forty seeds reach both kinds, so neither list went unchecked.
    assert kinds == {CHECKING, SAVINGS}


def test_samplers_run_in_declaration_order() -> None:
    samplers = LOADED_PACK.init_samplers
    kind_too_late = {
        (OPEN_ACCOUNT, relation): samplers[(OPEN_ACCOUNT, relation)]
        for relation in ("productName", "kind")
    }
    pack = replace(LOADED_PACK, init_samplers=kind_too_late)

    with pytest.raises(LookupError, match="kind"):
        Factory(0, pack).fill(unfilled_opening(), Registry())


def test_a_later_sampler_reads_a_value_the_init_fixes() -> None:
    by_status = {
        (OPEN_ACCOUNT, "kind"): ByValue(
            "hasStatus", {ACTIVE: Choice((SAVINGS,))}
        )
    }
    pack = replace(LOADED_PACK, init_samplers=by_status)

    filled = Factory(0, pack).fill(unfilled_opening(), Registry())

    assert isinstance(filled, InitCommand)
    assert filled.writes["kind"] == SAVINGS


@pytest.mark.parametrize("seed", SEEDS)
def test_a_filled_opening_is_accepted(seed: int) -> None:
    outcome = World().decide(filled_opening(Factory(seed, LOADED_PACK)))

    assert not isinstance(outcome, Refusal)


def test_the_same_seed_gives_the_same_openings() -> None:
    first, second = Factory(7, LOADED_PACK), Factory(7, LOADED_PACK)

    assert [filled_opening(first, s).writes for s in range(5)] == [
        filled_opening(second, s).writes for s in range(5)
    ]


def test_another_seed_gives_other_openings() -> None:
    first, second = Factory(7, LOADED_PACK), Factory(8, LOADED_PACK)

    assert [filled_opening(first, s).writes for s in range(5)] != [
        filled_opening(second, s).writes for s in range(5)
    ]


def test_each_fill_draws_on_from_the_last() -> None:
    factory = Factory(7, LOADED_PACK)

    assert filled_opening(factory).writes != filled_opening(factory).writes


def _allocate(world: World, count: int) -> None:
    """Take that many ids from the world's allocator."""

    for _ in range(count):
        world.allocator.allocate()


def _values_filled(seed: int, extra_ids: int) -> list[ValueClass]:
    """Each value a run fills, allocating extra ids before every command."""

    world = World()
    factory = Factory(seed, LOADED_PACK)

    # Before the opening too, so the account's own id differs between runs.
    _allocate(world, extra_ids)
    opening = filled_opening(factory)
    account = created_id(world.accept(opening))
    values = list(opening.writes.values())

    for session in (2, 3, 4):
        _allocate(world, extra_ids)

        step = _filled_mutate(
            factory, unfilled_fee_change(account, session), world.registry
        )
        world.accept(step)
        assert step.value is not None
        values.append(step.value)

    return values


def test_allocating_more_ids_changes_no_value() -> None:
    assert _values_filled(3, extra_ids=0) == _values_filled(3, extra_ids=25)


def test_an_opening_with_nothing_left_to_draw_is_refused() -> None:
    nothing = {(OPEN_ACCOUNT, "kind"): Choice((CHECKING,), weights=(0.0,))}
    pack = replace(LOADED_PACK, init_samplers=nothing)

    outcome = Factory(0, pack).fill(unfilled_opening(), Registry())

    assert outcome == FillRefusal(FillReason.NOTHING_LEFT_TO_DRAW)


def test_a_command_already_holding_values_raises() -> None:
    filled = filled_opening(Factory(0, LOADED_PACK))

    with pytest.raises(ValueError, match=OPEN_ACCOUNT):
        Factory(0, LOADED_PACK).fill(filled, Registry())


def test_an_init_command_naming_a_mutate_raises() -> None:
    command = replace(unfilled_opening(), action_type="CHANGE_ACCOUNT_FEE")

    with pytest.raises(TypeError, match="cannot take"):
        Factory(0, LOADED_PACK).fill(command, Registry())


def test_a_card_issue_keeps_its_links_and_fills_its_values() -> None:
    world = World()
    account = world.open()
    unfilled = replace(issue(account, 2), writes={})

    filled = Factory(0, LOADED_PACK).fill(unfilled, world.registry)

    assert isinstance(filled, InitCommand)
    assert filled.links == unfilled.links
    assert filled.writes["hasStatus"] == INACTIVE
    assert set(filled.writes) == {"hasStatus", "lastFour"}
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize(
    ("case_command", "kind"),
    [(report_fraud, "fraud_report"), (request_card, "card_request")],
    ids=["fraud report", "card request"],
)
def test_a_case_is_filled_with_the_kind_its_init_fixes(
    case_command: Callable[[NodeId, int], InitCommand], kind: str
) -> None:
    world = World()
    card = world.issue_card(world.open())
    unfilled = replace(case_command(card, REPORTED_IN), writes={})

    filled = Factory(0, LOADED_PACK).fill(unfilled, world.registry)

    assert isinstance(filled, InitCommand)
    assert filled.writes["kind"] == CaseKind(kind)
    assert filled.writes["hasStatus"] == OPEN
    assert set(filled.writes) == {"kind", "caseNumber", "hasStatus"}
    assert not isinstance(world.decide(filled), Refusal)


def test_filling_a_mutate_keeps_everything_but_the_value() -> None:
    world = World()
    command = unfilled_fee_change(world.open())

    filled = _filled_mutate(Factory(0, LOADED_PACK), command, world.registry)

    assert replace(filled, value=None) == command


@pytest.mark.parametrize("seed", SEEDS)
def test_a_new_rate_is_a_step_from_the_current_one(seed: int) -> None:
    world = World()
    account = world.open()

    filled = _filled_mutate(
        Factory(seed, LOADED_PACK), unfilled_reprice(account), world.registry
    )

    # The account opens at 4.25, and a savings rate tops out at 4.50.
    assert isinstance(filled.value, InterestRate)
    assert Decimal("3.75") <= filled.value.payload <= Decimal("4.50")
    assert filled.value != InterestRate(Decimal(OPENING_RATE))
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_step_follows_the_kind_the_entity_holds(seed: int) -> None:
    world = World()
    account = world.open(
        kind=CHECKING, hasInterestRate=InterestRate(Decimal("0.45"))
    )

    filled = _filled_mutate(
        Factory(seed, LOADED_PACK), unfilled_reprice(account), world.registry
    )

    # A savings rate could step above 0.50, a checking rate cannot.
    assert isinstance(filled.value, InterestRate)
    assert filled.value.payload <= Decimal("0.50")
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_new_fee_differs_from_the_current_one(seed: int) -> None:
    world = World()
    account = world.open()

    filled = _filled_mutate(
        Factory(seed, LOADED_PACK),
        unfilled_fee_change(account),
        world.registry,
    )

    assert filled.value in {
        MonetaryAmount(Decimal(fee)) for fee in ("0", "10", "12", "15")
    }
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_filled_mutate_is_accepted(seed: int) -> None:
    world = World()
    factory = Factory(seed, LOADED_PACK)
    account = created_id(world.accept(filled_opening(factory)))

    for session, unfilled in enumerate(
        (unfilled_reprice, unfilled_fee_change, unfilled_reprice), start=2
    ):
        command = unfilled(account, session)
        world.accept(_filled_mutate(factory, command, world.registry))


def test_a_status_move_is_left_to_the_status_it_fixes() -> None:
    world = World()
    account = world.open()
    command = move(account, 2, "FREEZE_DEPOSIT_ACCOUNT")

    filled = Factory(0, LOADED_PACK).fill(command, world.registry)

    assert filled == command
    assert not isinstance(world.decide(command), Refusal)


def test_a_mutate_on_no_such_entity_is_refused() -> None:
    outcome = Factory(0, LOADED_PACK).fill(
        unfilled_reprice(MISSING), Registry()
    )

    assert outcome == FillRefusal(FillReason.NO_CURRENT_VALUE)


def test_a_mutate_on_an_entity_of_another_type_is_refused() -> None:
    # Cards hold a last four too, so only the type tells this referent apart.
    renumber = MutateAction(
        "RENUMBER_ACCOUNT", referent_type="DEPOSIT_ACCOUNT", relation="lastFour"
    )
    pack = replace(
        with_action(LOADED_PACK, renumber),
        step_samplers={("DEPOSIT_ACCOUNT", "lastFour"): ANY_LAST_FOUR},
    )
    world = World(pack)
    card = world.issue_card(world.open())
    command = MutateCommand(
        session=3, initiator="BANK", action_type=renumber.name, referent=card
    )

    outcome = Factory(0, pack).fill(command, world.registry)

    assert outcome == FillRefusal(FillReason.NO_CURRENT_VALUE)


def test_a_mutate_of_a_relation_the_entity_lacks_is_refused() -> None:
    world = World()
    account = world.open_lacking("hasInterestRate")

    outcome = Factory(0, LOADED_PACK).fill(
        unfilled_reprice(account), world.registry
    )

    assert outcome == FillRefusal(FillReason.NO_CURRENT_VALUE)


def test_a_mutate_of_a_contested_value_is_refused() -> None:
    world = World()
    account = world.open()
    world.accept(contest(account, 2, "4.00", "4.10"))

    outcome = Factory(0, LOADED_PACK).fill(
        unfilled_reprice(account, 3), world.registry
    )

    assert outcome == FillRefusal(FillReason.NO_CURRENT_VALUE)


def test_a_contested_value_does_not_stop_a_step_of_another_relation() -> None:
    world = World()
    account = world.open()
    world.accept(contest(account, 2, "4.00", "4.10"))
    command = unfilled_fee_change(account, 3)

    filled = _filled_mutate(Factory(0, LOADED_PACK), command, world.registry)

    assert not isinstance(world.decide(filled), Refusal)


def test_a_step_reading_a_relation_the_entity_lacks_is_refused() -> None:
    world = World()
    account = world.open_lacking("kind")

    outcome = Factory(0, LOADED_PACK).fill(
        unfilled_reprice(account), world.registry
    )

    assert outcome == FillRefusal(FillReason.NO_VALUE_TO_READ)


def test_a_step_reading_a_contested_value_is_refused() -> None:
    rate_by_fee = ByValue(
        FEE, {WRITES[FEE]: Choice((InterestRate(Decimal(1)),))}
    )
    pack = replace(
        LOADED_PACK,
        step_samplers={("DEPOSIT_ACCOUNT", "hasInterestRate"): rate_by_fee},
    )
    world = World(pack)
    account = world.open()
    world.accept(fee_contest(account, 2))

    outcome = Factory(0, pack).fill(
        unfilled_reprice(account, 3), world.registry
    )

    assert outcome == FillRefusal(FillReason.NO_VALUE_TO_READ)


def test_a_step_with_nothing_left_to_draw_is_refused() -> None:
    only_the_current_fee = Choice((WRITES["hasMonthlyFee"],))
    pack = replace(
        LOADED_PACK,
        step_samplers={("DEPOSIT_ACCOUNT", FEE): only_the_current_fee},
    )
    world = World()
    account = world.open()

    outcome = Factory(0, pack).fill(
        unfilled_fee_change(account), world.registry
    )

    assert outcome == FillRefusal(FillReason.NOTHING_LEFT_TO_DRAW)


def test_a_mutate_already_holding_a_value_raises() -> None:
    world = World()
    account = world.open()

    with pytest.raises(ValueError, match="REPRICE_DEPOSIT_ACCOUNT"):
        Factory(0, LOADED_PACK).fill(
            reprice(account, 2, "4.00"), world.registry
        )


def test_a_mutate_command_naming_an_init_raises() -> None:
    world = World()
    account = world.open()
    command = replace(unfilled_reprice(account), action_type=OPEN_ACCOUNT)

    with pytest.raises(TypeError, match="cannot take"):
        Factory(0, LOADED_PACK).fill(command, world.registry)
