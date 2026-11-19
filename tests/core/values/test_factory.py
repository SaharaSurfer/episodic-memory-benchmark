import random
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from mbench.core.folds.registry import Registry, fold_world
from mbench.core.legality.predicate import Reason, Refusal, decide
from mbench.core.records.commands import (
    ConflictingDoubleDisclosureCommand,
    InitCommand,
    MutateCommand,
)
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import Record
from mbench.core.values.factory import (
    ConflictDraft,
    Factory,
    FillReason,
    FillRefusal,
)
from mbench.core.values.protocol import ValueClass
from mbench.core.values.samplers import (
    ByValue,
    Choice,
    DrawContext,
    Sampler,
)
from mbench.packs.spec import (
    LoadedPack,
    MutateAction,
)
from tests.core.records.handmade import OPEN_ACCOUNT
from tests.core.world import (
    BRANCH_PACK,
    FEE,
    LAST_FOURS,
    MISSING,
    OPEN_BRANCH,
    OPENED_IN,
    OPENING_RATE,
    RECODE_BRANCH,
    REPORTED_IN,
    WRITES,
    BranchName,
    World,
    contest,
    created_id,
    fee_contest,
    move,
    open_branch,
    report_fraud,
    reprice,
    request_card,
    unfilled_card,
    unfilled_fee_change,
    unfilled_opening,
    with_action,
    with_entity_type,
)
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK, PAYMENT_CARD
from tests.testpack.samplers import CHECKING, SAVINGS
from tests.testpack.values import (
    ACTIVE,
    CHECKING_PRODUCTS,
    INACTIVE,
    OPEN,
    SAVINGS_PRODUCTS,
    CaseKind,
    InterestRate,
    LastFour,
    MonetaryAmount,
    ProductName,
    ReferenceNumber,
)

SEEDS = range(40)

# Enough for a first draw that clashes, which is all a redraw test needs.
REDRAW_SEEDS = range(5)


def _filled_init(
    factory: Factory, command: InitCommand, registry: Registry
) -> InitCommand:
    """The factory's filling of an INIT it is expected to fill."""

    filled = factory.fill(command, registry)
    assert isinstance(filled, InitCommand)

    return filled


def _filled_opening(factory: Factory, session: int = OPENED_IN) -> InitCommand:
    """The factory's filling of an opening, on an empty registry."""

    return _filled_init(factory, unfilled_opening(session), Registry())


def _unfilled_reprice(account: NodeId, session: int = 2) -> MutateCommand:
    """A command repricing the account, the new rate not chosen yet."""

    return replace(reprice(account, session, "0"), value=None)


def _filled_mutate(
    factory: Factory, command: MutateCommand, registry: Registry
) -> MutateCommand:
    """The factory's filling of a MUTATE it is expected to fill."""

    filled = factory.fill(command, registry)
    assert isinstance(filled, MutateCommand)

    return filled


def test_an_opening_comes_back_with_every_relation_set() -> None:
    filled = _filled_opening(Factory(0, LOADED_PACK))

    assert set(filled.writes) == set(DEPOSIT_ACCOUNT.relations)


def test_filling_keeps_everything_but_the_writes() -> None:
    filled = _filled_opening(Factory(0, LOADED_PACK))

    assert replace(filled, writes={}) == unfilled_opening()


def test_an_opening_starts_in_the_status_the_init_fixes() -> None:
    writes = _filled_opening(Factory(0, LOADED_PACK)).writes

    assert writes["hasStatus"] == ACTIVE


def test_a_product_name_comes_from_the_list_of_the_kind_drawn() -> None:
    allowed: dict[ValueClass, set[ProductName]] = {
        CHECKING: set(map(ProductName, CHECKING_PRODUCTS)),
        SAVINGS: set(map(ProductName, SAVINGS_PRODUCTS)),
    }
    kinds = set()

    for seed in SEEDS:
        writes = _filled_opening(Factory(seed, LOADED_PACK)).writes
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

    filled = _filled_opening(Factory(0, pack))

    assert filled.writes["kind"] == SAVINGS


@pytest.mark.parametrize("seed", SEEDS)
def test_a_filled_opening_is_accepted(seed: int) -> None:
    outcome = World().decide(_filled_opening(Factory(seed, LOADED_PACK)))

    assert not isinstance(outcome, Refusal)


def test_the_same_seed_gives_the_same_openings() -> None:
    first, second = Factory(7, LOADED_PACK), Factory(7, LOADED_PACK)

    assert [_filled_opening(first, s).writes for s in range(5)] == [
        _filled_opening(second, s).writes for s in range(5)
    ]


def test_another_seed_gives_other_openings() -> None:
    first, second = Factory(7, LOADED_PACK), Factory(8, LOADED_PACK)

    assert [_filled_opening(first, s).writes for s in range(5)] != [
        _filled_opening(second, s).writes for s in range(5)
    ]


def test_each_fill_draws_on_from_the_last() -> None:
    factory = Factory(7, LOADED_PACK)

    assert _filled_opening(factory).writes != _filled_opening(factory).writes


def _allocate(allocator: IdAllocator, count: int) -> None:
    """Take that many ids from the allocator."""

    for _ in range(count):
        allocator.allocate()


def _accepted_records(
    command: InitCommand | MutateCommand,
    registry: Registry,
    allocator: IdAllocator,
) -> tuple[Record, ...]:
    """The records of a command the predicate is expected to accept."""

    outcome = decide(command, registry, LOADED_PACK, allocator)
    assert not isinstance(outcome, Refusal)

    return outcome.records


def _values_filled(seed: int, extra_ids: int) -> list[ValueClass]:
    """Each value a run fills, allocating extra ids before every command."""

    allocator = IdAllocator(seed=0)
    factory = Factory(seed, LOADED_PACK)

    # Before the opening too, so the account's own id differs between runs.
    _allocate(allocator, extra_ids)
    opening = _filled_opening(factory)
    records = _accepted_records(opening, Registry(), allocator)
    account = created_id(records)
    registry = fold_world(records, LOADED_PACK)
    values = list(opening.writes.values())

    for session in (2, 3, 4):
        _allocate(allocator, extra_ids)

        step = _filled_mutate(
            factory, _unfilled_reprice(account, session), registry
        )
        records = _accepted_records(step, registry, allocator)
        registry = fold_world(records, LOADED_PACK, registry)
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
    filled = _filled_opening(Factory(0, LOADED_PACK))

    with pytest.raises(ValueError, match=OPEN_ACCOUNT):
        Factory(0, LOADED_PACK).fill(filled, Registry())


def test_an_init_command_naming_a_mutate_raises() -> None:
    command = replace(unfilled_opening(), action_type="CHANGE_ACCOUNT_FEE")

    with pytest.raises(
        TypeError, match="InitCommand cannot take CHANGE_ACCOUNT_FEE"
    ):
        Factory(0, LOADED_PACK).fill(command, Registry())


def test_a_card_issue_keeps_its_links_and_fills_its_values() -> None:
    world = World()
    account = world.open()
    unfilled = unfilled_card(account)

    filled = _filled_init(Factory(0, LOADED_PACK), unfilled, world.registry)

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

    filled = _filled_init(Factory(0, LOADED_PACK), unfilled, world.registry)

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
        Factory(seed, LOADED_PACK), _unfilled_reprice(account), world.registry
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
        Factory(seed, LOADED_PACK), _unfilled_reprice(account), world.registry
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
    account = created_id(world.accept(_filled_opening(factory)))

    for session, unfilled in enumerate(
        (_unfilled_reprice, unfilled_fee_change, _unfilled_reprice), start=2
    ):
        command = unfilled(account, session)
        world.accept(_filled_mutate(factory, command, world.registry))


def test_a_status_move_is_left_to_the_status_it_fixes() -> None:
    world = World()
    account = world.open()
    command = move(account, 2, "FREEZE_DEPOSIT_ACCOUNT")

    filled = Factory(0, LOADED_PACK).fill(command, world.registry)

    assert filled == command


def test_a_mutate_on_no_such_entity_is_refused() -> None:
    outcome = Factory(0, LOADED_PACK).fill(
        _unfilled_reprice(MISSING), Registry()
    )

    assert outcome == FillRefusal(FillReason.NO_CURRENT_VALUE)


def test_a_mutate_on_an_entity_of_another_type_is_refused() -> None:
    # Cards hold a last four too, so only the type tells this referent apart.
    renumber = MutateAction(
        "RENUMBER_ACCOUNT", referent_type="DEPOSIT_ACCOUNT", relation="lastFour"
    )
    pack = with_action(LOADED_PACK, renumber)
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
        _unfilled_reprice(account), world.registry
    )

    assert outcome == FillRefusal(FillReason.NO_CURRENT_VALUE)


def test_a_mutate_of_a_contested_value_is_refused() -> None:
    world = World()
    account = world.open()
    world.accept(contest(account, 2, "4.00", "4.10"))

    outcome = Factory(0, LOADED_PACK).fill(
        _unfilled_reprice(account, 3), world.registry
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
        _unfilled_reprice(account), world.registry
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
        _unfilled_reprice(account, 3), world.registry
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
    command = replace(_unfilled_reprice(account), action_type=OPEN_ACCOUNT)

    with pytest.raises(
        TypeError, match=f"MutateCommand cannot take {OPEN_ACCOUNT}"
    ):
        Factory(0, LOADED_PACK).fill(command, world.registry)


class Scripted:
    """A sampler giving the listed values in turn, then the last for good."""

    def __init__(self, *values: ValueClass) -> None:
        """Hold the values, none drawn yet."""

        self.values = values
        self.draws = 0

    def draw(
        self, stream: random.Random, context: DrawContext
    ) -> ValueClass | None:
        """The next listed value."""

        value = self.values[min(self.draws, len(self.values) - 1)]
        self.draws += 1

        return value


MAIN = BranchName("Main")
HARBOR = BranchName("Harbor")
TAKEN_CASE = ReferenceNumber("48213")
ALSO_TAKEN_CASE = ReferenceNumber("48214")
FREE_CASE = ReferenceNumber("48215")
OTHER_FREE_CASE = ReferenceNumber("48216")
OWN_CASE = ReferenceNumber("48217")
TAKEN_FOUR = LastFour(LAST_FOURS[0])
FREE_FOUR = LastFour(LAST_FOURS[1])


def _with_sampler(
    action: str,
    relation: str,
    sampler: Sampler[Any],
    pack: LoadedPack = LOADED_PACK,
) -> LoadedPack:
    """The pack with the INIT drawing the relation from the sampler."""

    return replace(
        pack,
        init_samplers={**pack.init_samplers, (action, relation): sampler},
    )


def _branch_pack(**samplers: Sampler[Any]) -> LoadedPack:
    """The branch pack, an opening drawing exactly these relations."""

    return replace(
        BRANCH_PACK,
        init_samplers={
            (OPEN_BRANCH, relation): sampler
            for relation, sampler in samplers.items()
        },
    )


def _unfilled_branch() -> InitCommand:
    """A command opening a branch, no value of it chosen yet."""

    return open_branch()


def _recoding(branch: NodeId) -> MutateCommand:
    """A command giving the branch a new code, not chosen yet."""

    return MutateCommand(
        session=2,
        initiator="BANK",
        action_type=RECODE_BRANCH.name,
        source="letter",
        referent=branch,
    )


def _recode_pack(sampler: Sampler[Any]) -> LoadedPack:
    """The branch pack, recoding a branch by the sampler."""

    return replace(BRANCH_PACK, step_samplers={("BRANCH", "code"): sampler})


def _second_branch(world: World) -> NodeId:
    """Open a branch holding the taken code, then one to recode, its id."""

    world.accept(open_branch(name=MAIN, code=TAKEN_CASE))

    return created_id(world.accept(open_branch(name=HARBOR, code=OWN_CASE)))


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_a_scenario_identifier_is_redrawn_off_another_types_value(
    seed: int,
) -> None:
    pool = Choice((TAKEN_FOUR, FREE_FOUR))
    pack = _with_sampler("ISSUE_CARD", "lastFour", pool)
    world = World(pack)
    account = world.open(lastFour=TAKEN_FOUR)

    filled = _filled_init(
        Factory(seed, pack), unfilled_card(account), world.registry
    )

    assert filled.writes["lastFour"] == FREE_FOUR
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_a_closed_entity_keeps_its_identifier_taken(seed: int) -> None:
    pool = Choice((TAKEN_FOUR, FREE_FOUR))
    pack = _with_sampler("ISSUE_CARD", "lastFour", pool)
    world = World(pack)
    account = world.open(lastFour=TAKEN_FOUR)
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    filled = _filled_init(
        Factory(seed, pack), unfilled_card(account), world.registry
    )

    assert filled.writes["lastFour"] == FREE_FOUR


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_both_values_of_a_contested_identifier_stay_taken(seed: int) -> None:
    pool = Choice((TAKEN_CASE, ALSO_TAKEN_CASE, FREE_CASE))
    pack = _branch_pack(name=Choice((HARBOR,)), code=pool)
    world = World(pack)
    branch = created_id(world.accept(open_branch(name=MAIN, code=OWN_CASE)))
    world.accept(
        ConflictingDoubleDisclosureCommand(
            session=2,
            initiator="BANK",
            referent=branch,
            relation="code",
            a=TAKEN_CASE,
            b=ALSO_TAKEN_CASE,
            sources=("letter", "email"),
        )
    )

    # Two draws in three clash, so the default limit could run out.
    filled = _filled_init(
        Factory(seed, pack, redraw_limit=100),
        _unfilled_branch(),
        world.registry,
    )

    assert filled.writes["code"] == FREE_CASE


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_a_type_identifier_is_redrawn_off_its_own_types_value(
    seed: int,
) -> None:
    # Another kind of case, so the anchors differ and only the scope clashes.
    pool = Choice((TAKEN_CASE, FREE_CASE))
    pack = _with_sampler("REQUEST_CARD", "caseNumber", pool)
    world = World(pack)
    card = world.issue_card(world.open())
    world.accept(report_fraud(card, REPORTED_IN, caseNumber=TAKEN_CASE))
    unfilled = replace(request_card(card, REPORTED_IN + 1), writes={})

    filled = _filled_init(Factory(seed, pack), unfilled, world.registry)

    assert filled.writes["caseNumber"] == FREE_CASE
    assert not isinstance(world.decide(filled), Refusal)


def test_a_type_identifier_may_equal_another_types_value() -> None:
    only_the_branch_code = Choice((TAKEN_CASE,))
    pack = _with_sampler(
        "REPORT_FRAUD", "caseNumber", only_the_branch_code, BRANCH_PACK
    )
    world = World(pack)
    account = world.open()
    world.accept(open_branch(name=MAIN, code=TAKEN_CASE))
    unfilled = replace(report_fraud(account, REPORTED_IN), writes={})

    filled = _filled_init(Factory(0, pack), unfilled, world.registry)

    assert filled.writes["caseNumber"] == TAKEN_CASE


def test_a_value_without_a_scope_may_repeat() -> None:
    only_the_held_fee = Choice((WRITES[FEE],))
    pack = _with_sampler(OPEN_ACCOUNT, FEE, only_the_held_fee)
    world = World(pack)
    world.open()

    filled = _filled_init(Factory(0, pack), unfilled_opening(), world.registry)

    assert filled.writes[FEE] == WRITES[FEE]


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_two_identifiers_of_one_command_differ(seed: int) -> None:
    pool = Choice((FREE_CASE, OTHER_FREE_CASE))
    pack = _branch_pack(name=Choice((MAIN,)), code=pool, spareCode=pool)

    filled = _filled_init(Factory(seed, pack), _unfilled_branch(), Registry())

    assert filled.writes["code"] != filled.writes["spareCode"]


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_an_anchor_in_an_existing_same_zone_is_redrawn(seed: int) -> None:
    # Equal to nothing the world holds, so only the zone can catch it.
    pool = Choice((BranchName("MAIN"), HARBOR))
    pack = _branch_pack(name=pool)
    world = World(pack)
    world.accept(open_branch(name=MAIN))

    filled = _filled_init(
        Factory(seed, pack), _unfilled_branch(), world.registry
    )

    assert filled.writes["name"] == HARBOR
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_a_value_read_from_a_redrawn_anchor_follows_it(seed: int) -> None:
    code_by_name = ByValue(
        "name",
        {
            MAIN: Choice((OTHER_FREE_CASE,)),
            HARBOR: Choice((FREE_CASE,)),
        },
    )
    pack = _branch_pack(name=Choice((MAIN, HARBOR)), code=code_by_name)
    world = World(pack)
    world.accept(open_branch(name=MAIN))

    filled = _filled_init(
        Factory(seed, pack), _unfilled_branch(), world.registry
    )

    assert filled.writes["name"] == HARBOR
    assert filled.writes["code"] == FREE_CASE


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_a_mutate_identifier_is_redrawn_off_other_entities(seed: int) -> None:
    pack = _recode_pack(Choice((TAKEN_CASE, FREE_CASE)))
    world = World(pack)
    branch = _second_branch(world)

    filled = _filled_mutate(
        Factory(seed, pack), _recoding(branch), world.registry
    )

    assert filled.value == FREE_CASE
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("seed", REDRAW_SEEDS)
def test_a_conflict_identifier_is_redrawn_off_other_entities(seed: int) -> None:
    pack = _recode_pack(Choice((TAKEN_CASE, FREE_CASE, OTHER_FREE_CASE)))
    world = World(pack)
    branch = _second_branch(world)
    draft = ConflictDraft(
        session=2,
        initiator="BANK",
        referent=branch,
        relation="code",
        sources=("letter", "email"),
    )

    # Two pairs in three hold the taken code, so the default limit could run
    # out.
    filled = Factory(seed, pack, redraw_limit=100).fill(draft, world.registry)

    assert isinstance(filled, ConflictingDoubleDisclosureCommand)
    assert {filled.a, filled.b} == {FREE_CASE, OTHER_FREE_CASE}
    assert not isinstance(world.decide(filled), Refusal)


@pytest.mark.parametrize("limit", [0, 2])
def test_an_init_succeeds_on_its_last_allowed_redraw(limit: int) -> None:
    sampler = Scripted(*[MAIN] * limit, HARBOR)
    pack = _branch_pack(name=sampler)
    world = World(pack)
    world.accept(open_branch(name=MAIN))

    filled = _filled_init(
        Factory(0, pack, redraw_limit=limit),
        _unfilled_branch(),
        world.registry,
    )

    assert filled.writes["name"] == HARBOR


@pytest.mark.parametrize("limit", [0, 2])
def test_an_init_is_refused_past_the_redraw_limit(limit: int) -> None:
    sampler = Scripted(*[MAIN] * (limit + 1), HARBOR)
    pack = _branch_pack(name=sampler)
    world = World(pack)
    world.accept(open_branch(name=MAIN))

    outcome = Factory(0, pack, redraw_limit=limit).fill(
        _unfilled_branch(), world.registry
    )

    assert outcome == FillRefusal(FillReason.ANCHOR_SAME_ZONE)
    assert sampler.draws == limit + 1


def test_a_refusal_names_the_clash_of_the_last_draw() -> None:
    pack = _branch_pack(
        name=Scripted(MAIN, HARBOR), code=Scripted(FREE_CASE, TAKEN_CASE)
    )
    world = World(pack)
    world.accept(open_branch(name=MAIN, code=TAKEN_CASE))

    outcome = Factory(0, pack, redraw_limit=1).fill(
        _unfilled_branch(), world.registry
    )

    assert outcome == FillRefusal(FillReason.IDENTIFIER_TAKEN)


@pytest.mark.parametrize("limit", [0, 2])
def test_a_mutate_succeeds_on_its_last_allowed_redraw(limit: int) -> None:
    pack = _recode_pack(Scripted(*[TAKEN_CASE] * limit, FREE_CASE))
    world = World(pack)
    branch = _second_branch(world)

    filled = _filled_mutate(
        Factory(0, pack, redraw_limit=limit),
        _recoding(branch),
        world.registry,
    )

    assert filled.value == FREE_CASE


@pytest.mark.parametrize("limit", [0, 2])
def test_a_mutate_is_refused_past_the_redraw_limit(limit: int) -> None:
    sampler = Scripted(TAKEN_CASE)
    pack = _recode_pack(sampler)
    world = World(pack)
    branch = _second_branch(world)

    outcome = Factory(0, pack, redraw_limit=limit).fill(
        _recoding(branch), world.registry
    )

    assert outcome == FillRefusal(FillReason.IDENTIFIER_TAKEN)
    assert sampler.draws == limit + 1


def test_a_pool_of_taken_identifiers_ends_in_a_refusal() -> None:
    pack = _with_sampler("ISSUE_CARD", "lastFour", Choice((TAKEN_FOUR,)))
    world = World(pack)
    account = world.open(lastFour=TAKEN_FOUR)

    outcome = Factory(0, pack).fill(unfilled_card(account), world.registry)

    assert outcome == FillRefusal(FillReason.IDENTIFIER_TAKEN)


def test_an_init_whose_links_do_not_match_its_action_raises() -> None:
    world = World()
    account = world.open()
    unlinked = replace(unfilled_card(account), links={})

    with pytest.raises(ValueError, match="ISSUE_CARD takes links"):
        Factory(0, LOADED_PACK).fill(unlinked, world.registry)


def test_an_init_with_a_missing_endpoint_is_left_to_decide() -> None:
    # Every card is issued inactive, so a status anchor clashes on every draw.
    pack = with_entity_type(
        LOADED_PACK,
        replace(PAYMENT_CARD, anchor=("hasStatus",), nameable=False),
    )
    world = World(pack)
    account = world.open()
    world.issue_card(account)
    clashing = Factory(0, pack).fill(unfilled_card(account), world.registry)

    filled = Factory(0, pack).fill(unfilled_card(MISSING), world.registry)

    assert clashing == FillRefusal(FillReason.ANCHOR_SAME_ZONE)

    assert isinstance(filled, InitCommand)
    assert world.decide(filled) == Refusal(Reason.ENDPOINT_MISSING)


def test_a_negative_redraw_limit_raises() -> None:
    with pytest.raises(ValueError, match="redraw limit"):
        Factory(0, LOADED_PACK, redraw_limit=-1)
