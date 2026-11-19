from mbench.core.folds.registry import fold_world
from mbench.core.legality.predicate import Reason, Refusal, decide
from mbench.core.legality.replay import IllegalPosition, replay
from mbench.core.records.commands import (
    ConflictingDoubleDisclosureCommand,
    MutateCommand,
)
from mbench.core.records.ids import IdAllocator
from mbench.core.records.log import Log
from tests.core.world import (
    BRANCH_PACK,
    CARD_WRITES,
    CASE_WRITES,
    ISSUED_IN,
    RECODE_BRANCH,
    REPORTED_IN,
    World,
    created_id,
    issue,
    move,
    open_account,
    open_branch,
    report_fraud,
    request_card,
)
from tests.testpack.values import ReferenceNumber

TAKEN = Refusal(Reason.IDENTIFIER_TAKEN)
CARD_FOUR = CARD_WRITES["lastFour"]

# The default case number, which the world's cases all take.
CASE_NUMBER = CASE_WRITES["caseNumber"]


def test_a_scenario_identifier_held_by_another_type_is_refused() -> None:
    world = World()
    world.open(lastFour=CARD_FOUR)
    account = world.open()

    outcome = world.decide(issue(account, ISSUED_IN))

    assert outcome == TAKEN


def test_a_card_whose_last_four_is_free_is_accepted() -> None:
    world = World()
    account = world.open()

    outcome = world.decide(issue(account, ISSUED_IN))

    assert not isinstance(outcome, Refusal)


def test_a_type_identifier_held_by_its_own_type_is_refused() -> None:
    world = World()
    card = world.issue_card(world.open())
    world.accept(report_fraud(card, REPORTED_IN, caseNumber=CASE_NUMBER))

    # Another kind of case, so the anchors differ and only the scope clashes.
    outcome = world.decide(
        request_card(card, REPORTED_IN + 1, caseNumber=CASE_NUMBER)
    )

    assert outcome == TAKEN


def test_a_type_identifier_may_equal_another_types_value() -> None:
    world = World(BRANCH_PACK)
    card = world.issue_card(world.open())
    world.accept(open_branch(ISSUED_IN, code=CASE_NUMBER))

    outcome = world.decide(
        report_fraud(card, REPORTED_IN, caseNumber=CASE_NUMBER)
    )

    assert not isinstance(outcome, Refusal)


def test_two_equal_identifiers_in_one_init_are_refused() -> None:
    world = World(BRANCH_PACK)

    outcome = world.decide(open_branch(code=CASE_NUMBER, spareCode=CASE_NUMBER))

    assert outcome == TAKEN


def test_a_closed_entity_keeps_its_identifier() -> None:
    world = World()
    account = world.open(lastFour=CARD_FOUR)
    other = world.open()
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(issue(other, 3))

    assert outcome == TAKEN


def test_both_sides_of_a_contested_identifier_are_held() -> None:
    world = World(BRANCH_PACK)
    branch = created_id(
        world.accept(open_branch(code=ReferenceNumber("10001")))
    )
    world.accept(
        ConflictingDoubleDisclosureCommand(
            session=2,
            initiator="BANK",
            referent=branch,
            relation="code",
            a=ReferenceNumber("10003"),
            b=ReferenceNumber("10004"),
            sources=("letter", "email"),
        )
    )

    outcomes = [
        world.decide(open_branch(3, code=ReferenceNumber(code)))
        for code in ("10003", "10004")
    ]

    assert outcomes == [TAKEN, TAKEN]


def test_a_mutate_writing_a_held_identifier_is_refused() -> None:
    world = World(BRANCH_PACK)
    world.accept(open_branch(code=ReferenceNumber("10001")))
    branch = created_id(
        world.accept(open_branch(code=ReferenceNumber("10002")))
    )

    outcome = world.decide(
        MutateCommand(
            session=2,
            initiator="BANK",
            action_type=RECODE_BRANCH.name,
            source="letter",
            referent=branch,
            value=ReferenceNumber("10001"),
        )
    )

    assert outcome == TAKEN


def test_a_contest_writing_a_held_identifier_is_refused() -> None:
    world = World(BRANCH_PACK)
    world.accept(open_branch(code=ReferenceNumber("10001")))
    branch = created_id(
        world.accept(open_branch(code=ReferenceNumber("10002")))
    )

    outcome = world.decide(
        ConflictingDoubleDisclosureCommand(
            session=2,
            initiator="BANK",
            referent=branch,
            relation="code",
            a=ReferenceNumber("10004"),
            b=ReferenceNumber("10001"),
            sources=("letter", "email"),
        )
    )

    assert outcome == TAKEN


def test_replay_refuses_the_later_init_an_insertion_clashes_with() -> None:
    world = World()
    account = world.open()
    world.accept(issue(account, 3))
    first, card = world.log.accepted
    registry = fold_world(first.records, world.pack)

    # Seeded apart from the world's, whose ids this seed happens not to repeat.
    injected = decide(
        open_account(2, lastFour=CARD_FOUR),
        registry,
        world.pack,
        IdAllocator(seed=1),
    )
    assert not isinstance(injected, Refusal)
    merged = Log().append((first, injected, card))

    assert replay(merged, world.pack) == IllegalPosition(2, TAKEN)
