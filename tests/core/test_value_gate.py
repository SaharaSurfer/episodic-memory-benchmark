from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.records.commands import InitCommand, MutateCommand
from mbench.core.records.ids import NodeId
from tests.core.world import World, created_id
from tests.valuegate.pack import (
    KEEPER,
    LIGHT_LANTERN,
    LOADED_PACK,
    LONG,
    MEDIUM,
    SHORT,
    TRIM_WICK,
    WICK_LENGTH,
    WickLength,
)

GATE_FAILED = Refusal(Reason.GATE_FAILED)


def _light_lantern(world: World, wick: WickLength) -> NodeId:
    records = world.accept(
        InitCommand(
            session=1,
            initiator=KEEPER.name,
            action_type=LIGHT_LANTERN,
            writes={WICK_LENGTH: wick},
        )
    )

    return created_id(records)


def _trim(lantern: NodeId, session: int, wick: WickLength) -> MutateCommand:
    return MutateCommand(
        session=session,
        initiator=KEEPER.name,
        action_type=TRIM_WICK,
        referent=lantern,
        value=wick,
    )


def test_the_gated_command_is_accepted_when_the_value_passes() -> None:
    world = World(LOADED_PACK)
    lantern = _light_lantern(world, LONG)

    outcome = world.decide(_trim(lantern, 2, SHORT))

    assert not isinstance(outcome, Refusal)


def test_the_gated_command_is_refused_when_the_value_fails() -> None:
    world = World(LOADED_PACK)
    lantern = _light_lantern(world, SHORT)

    outcome = world.decide(_trim(lantern, 2, MEDIUM))

    assert outcome == GATE_FAILED


def test_a_mutate_that_changes_the_value_changes_the_gates_answer() -> None:
    world = World(LOADED_PACK)
    lantern = _light_lantern(world, LONG)

    # Accepting it fails on a refusal, so the gate was open until now.
    world.accept(_trim(lantern, 2, SHORT))
    outcome = world.decide(_trim(lantern, 3, MEDIUM))

    assert outcome == GATE_FAILED
