from collections import Counter
from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

from mbench.core.folds.graph import fold_trace
from mbench.core.records.log import Disclosure, InitEvent, Log
from tests.core.generated_log import Shape, generate_log, shape_of
from tests.core.inserted_log import ExtendedLog, insert_commands
from tests.testpack.pack import LOADED_PACK

# Base logs as long as the fold properties' own, so insertions land among
# entities that are moved, read and contested.
MAX_STEPS = 80
MAX_ATTEMPTS = 20

# Seeds for the coverage check, the attempts on each, and how often it must
# see each case there. A contest is refused at most boundaries, since it
# seals its pair, so it needs many more attempts than the properties make.
COVERAGE_SEEDS = 20
COVERAGE_ATTEMPTS = 120
MIN_REACHED = 10

# A log is slow to fold, and its length varies, so no example has a deadline.
no_deadline = settings(deadline=None)


@dataclass(frozen=True)
class Extension:
    """A base log, and the extended log built from it."""

    base: Log
    extended: ExtendedLog


def _extend(base_seed: int, steps: int, seed: int, attempts: int) -> Extension:
    """A generated base log and the same log with commands inserted."""

    base = generate_log(base_seed, steps).log

    return Extension(base, insert_commands(base, seed, attempts))


seeds = st.integers(min_value=0, max_value=2**32 - 1)
extensions = st.builds(
    _extend,
    base_seed=seeds,
    steps=st.integers(min_value=0, max_value=MAX_STEPS),
    seed=seeds,
    attempts=st.integers(min_value=0, max_value=MAX_ATTEMPTS),
)


@no_deadline
@given(extensions)
def test_the_extended_graph_contains_every_base_node_and_edge(
    extension: Extension,
) -> None:
    base = fold_trace(extension.base.records, LOADED_PACK)
    extended = fold_trace(extension.extended.log.records, LOADED_PACK)

    assert extended.contains(base)
    # Containment compares nodes by id alone, so this adds what each holds.
    assert base.entity_nodes() <= extended.entity_nodes()
    assert base.value_nodes() <= extended.value_nodes()


@no_deadline
@given(extensions)
def test_the_base_commands_stay_in_order_and_unchanged(
    extension: Extension,
) -> None:
    extended = extension.extended
    kept = tuple(
        accepted
        for position, accepted in enumerate(extended.log.accepted)
        if position not in extended.inserted
    )

    assert kept == extension.base.accepted


@no_deadline
@given(extensions)
def test_no_id_is_allocated_twice_in_an_extended_log(
    extension: Extension,
) -> None:
    # A list, not a set: a set would hide two inserted records sharing an id,
    # as well as an inserted record taking a base id.
    allocated = [
        record.new_id if isinstance(record, InitEvent) else record.node_id
        for record in extension.extended.log.records
        if isinstance(record, InitEvent | Disclosure)
    ]

    assert len(set(allocated)) == len(allocated)


@no_deadline
@given(extensions)
def test_sessions_never_go_down_in_an_extended_log(
    extension: Extension,
) -> None:
    sessions = [
        accepted.command.session for accepted in extension.extended.log.accepted
    ]

    assert sessions == sorted(sessions)


def test_insertions_reach_every_shape_and_mid_session_and_some_fail() -> None:
    shapes: Counter[Shape] = Counter()
    mid_session = 0
    discarded = 0

    for seed in range(COVERAGE_SEEDS):
        base = generate_log(seed, MAX_STEPS).log
        extended = insert_commands(base, seed, COVERAGE_ATTEMPTS)
        accepted = extended.log.accepted
        base_positions = [
            position
            for position in range(len(accepted))
            if position not in extended.inserted
        ]

        for position in extended.inserted:
            command = accepted[position].command
            shapes[shape_of(command, LOADED_PACK)] += 1
            before = [p for p in base_positions if p < position]
            after = [p for p in base_positions if p > position]
            # Between two base commands of its own session, so a base command
            # of that session is re-checked after it.
            mid_session += bool(
                before
                and after
                and accepted[before[-1]].command.session
                == command.session
                == accepted[after[0]].command.session
            )

        discarded += extended.discarded

    # Every shape often, so no kind of addition goes untested.
    assert min(shapes[shape] for shape in Shape) >= MIN_REACHED
    assert mid_session >= MIN_REACHED
    # Some insertions break a later base command, so the replay has teeth.
    assert discarded >= MIN_REACHED
