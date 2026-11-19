import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from mbench.core.folds.graph import EdgeKind, Pair, fold_trace
from mbench.core.folds.registry import fold_world
from mbench.core.legality.replay import replay
from mbench.core.records.ids import NodeId
from mbench.core.records.log import (
    Disclosure,
    InitEvent,
    Link,
    Log,
    MutateEvent,
)
from mbench.core.values.contested import Contested, WorldValue
from mbench.core.values.protocol import ValueClass
from tests.core.generated_log import (
    GeneratedLog,
    Shape,
    canonical,
    generate_log,
    shape_of,
)
from tests.testpack.pack import LOADED_PACK

# Long enough for an entity to be created, moved, read and contested.
MAX_STEPS = 80

# Seeds for the coverage check, and how often it must see each shape there.
COVERAGE_SEEDS = 20
MIN_REACHED = 10

# Seeds generated in each fresh process, and the hash seeds those run under.
DETERMINISM_SEEDS = 5
HASH_SEEDS = ("1", "2")

ROOT = Path(__file__).resolve().parents[2]

# Prints the first seeds' logs, one a line, for a fresh process to run.
GENERATE_AND_PRINT = f"""
from tests.core.generated_log import canonical, generate_log
for seed in range({DETERMINISM_SEEDS}):
    print(canonical(generate_log(seed, {MAX_STEPS}).log))
"""

# A log is slow to fold, and its length varies, so no example has a deadline.
no_deadline = settings(deadline=None)

logs = st.builds(
    generate_log,
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    steps=st.integers(min_value=0, max_value=MAX_STEPS),
)


def _held(value: WorldValue) -> frozenset[ValueClass]:
    """The plain values a pair holds, both sides of a conflict included."""

    return value.members if isinstance(value, Contested) else frozenset({value})


@no_deadline
@given(logs)
def test_every_disclosed_pair_holds_the_graphs_latest_value(
    generated_log: GeneratedLog,
) -> None:
    records = generated_log.log.records
    registry = fold_world(records, LOADED_PACK)
    graph = fold_trace(records, LOADED_PACK)
    pairs = {
        (record.entity, record.relation)
        for record in records
        if isinstance(record, Disclosure) and not isinstance(record.value, Link)
    }

    for entity, relation in pairs:
        entry = registry.entry(entity)
        assert entry is not None
        latest = {node.value for node in graph.latest((entity, relation))}

        assert latest == _held(entry.values[relation].value)


@no_deadline
@given(logs)
def test_every_disclosed_link_is_the_registrys_link(
    generated_log: GeneratedLog,
) -> None:
    records = generated_log.log.records
    registry = fold_world(records, LOADED_PACK)
    graph = fold_trace(records, LOADED_PACK)
    structural = {
        (edge.source, edge.relation): edge.target
        for edge in graph.edges()
        if edge.kind is EdgeKind.STRUCTURAL
    }
    links = {
        (entry.id, relation): target
        for entry in registry.entries()
        for relation, target in entry.links.items()
    }

    # A link has no value node, so its latest value is the edge itself.
    assert structural == links


@no_deadline
@given(logs)
def test_every_generated_log_replays_clean(
    generated_log: GeneratedLog,
) -> None:
    assert replay(generated_log.log, LOADED_PACK) is None


@no_deadline
@given(logs)
def test_the_registry_built_step_by_step_is_the_fold_of_the_log(
    generated_log: GeneratedLog,
) -> None:
    folded = fold_world(generated_log.log.records, LOADED_PACK)

    assert generated_log.registry == folded


@no_deadline
@given(logs)
def test_a_pairs_version_count_is_the_number_of_writes_to_it(
    generated_log: GeneratedLog,
) -> None:
    records = generated_log.log.records
    graph = fold_trace(records, LOADED_PACK)
    writes: Counter[Pair] = Counter()

    # A conflict writes both its values, each a version of its own.
    for record in records:
        if isinstance(record, InitEvent):
            writes.update(
                (record.new_id, relation) for relation in record.writes
            )
        elif isinstance(record, MutateEvent):
            for relation, written in record.writes.items():
                writes[(record.referent, relation)] += len(_held(written))

    value_edges = Counter(
        (edge.source, edge.relation)
        for edge in graph.edges()
        if edge.kind is EdgeKind.VALUE
    )

    assert value_edges == writes
    for pair, count in writes.items():
        assert graph.versions(pair) == count


@no_deadline
@given(logs)
def test_every_node_occurs_in_exactly_one_session_and_ids_are_unique(
    generated_log: GeneratedLog,
) -> None:
    records = generated_log.log.records
    graph = fold_trace(records, LOADED_PACK)
    nodes = [node.id for node in graph.entity_nodes()] + [
        node.id for node in graph.value_nodes()
    ]
    occurred_in = Counter(
        edge.source
        for edge in graph.edges()
        if edge.kind is EdgeKind.OCCURRED_IN
    )
    allocated = [
        record.new_id if isinstance(record, InitEvent) else record.node_id
        for record in records
        if isinstance(record, InitEvent | Disclosure)
    ]

    # The graph keys its nodes and their `occurredIn` by id, so these two only
    # catch an entity and a value node sharing an id, or a node with no
    # session. The allocated ids are the check with teeth: a reused id would
    # merge two nodes, which the graph alone could not show.
    assert len(set(nodes)) == len(nodes)
    assert occurred_in == Counter(nodes)
    assert len(set(allocated)) == len(allocated)


def _logs_in_a_fresh_process(hash_seed: str) -> list[str]:
    """The first seeds' logs, written out under the hash seed given."""

    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(ROOT)}
    done = subprocess.run(
        [sys.executable, "-c", GENERATE_AND_PRINT],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr

    return done.stdout.splitlines()


def test_the_same_seed_gives_the_same_log() -> None:
    # In separate processes, so a log built in set order shows: one process
    # hashes strings the same way every time, and would hide it.
    first, second = (_logs_in_a_fresh_process(seed) for seed in HASH_SEEDS)

    assert len(first) == DETERMINISM_SEEDS
    assert first == second


def test_equal_logs_are_written_alike() -> None:
    log = generate_log(0, MAX_STEPS).log

    assert canonical(generate_log(0, MAX_STEPS).log) == canonical(log)
    assert canonical(generate_log(1, MAX_STEPS).log) != canonical(log)


def test_generated_logs_reach_every_command_shape() -> None:
    reached: Counter[Shape] = Counter()
    rewritten = 0
    contested = 0

    for seed in range(COVERAGE_SEEDS):
        generated_log = generate_log(seed, MAX_STEPS)
        reached.update(
            shape_of(accepted.command, LOADED_PACK)
            for accepted in generated_log.log.accepted
        )
        rewritten += len(_pairs_written_in_two_sessions(generated_log.log))
        contested += any(
            isinstance(stamped.value, Contested)
            for entry in generated_log.registry.entries()
            for stamped in entry.values.values()
        )

    # Every shape often, not once, so a starved shape shows up here.
    assert min(reached[shape] for shape in Shape) >= MIN_REACHED
    # A pair written in two sessions, so its latest value is not its first.
    assert rewritten >= MIN_REACHED
    # The invariant's contested case: a conflict the log ends holding.
    assert contested >= MIN_REACHED


def _pairs_written_in_two_sessions(log: Log) -> set[Pair]:
    """The pairs whose value nodes entered the graph in two or more sessions."""

    graph = fold_trace(log.records, LOADED_PACK)
    session_of: dict[NodeId | int, NodeId | int] = {
        edge.source: edge.target
        for edge in graph.edges()
        if edge.kind is EdgeKind.OCCURRED_IN
    }
    sessions: dict[Pair, set[NodeId | int]] = {}
    for edge in graph.edges():
        if edge.kind is EdgeKind.VALUE:
            assert edge.relation is not None
            pair = (edge.source, edge.relation)
            sessions.setdefault(pair, set()).add(session_of[edge.target])

    return {pair for pair, seen in sessions.items() if len(seen) > 1}
