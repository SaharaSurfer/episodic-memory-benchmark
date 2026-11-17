from mbench.core.folds.graph import Graph, fold_trace
from mbench.core.folds.registry import Registry, fold_world
from mbench.core.records.ids import NodeId
from mbench.core.records.log import Disclosure, InitEvent, Record
from mbench.core.values.protocol import ValueClass
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import LastFour


def _opened(entity: str, node: str, value: ValueClass) -> tuple[Record, ...]:
    return (
        InitEvent(
            session=1,
            initiator="client",
            action_type="OPEN_DEPOSIT_ACCOUNT",
            new_id=NodeId(entity),
            writes={"lastFour": value},
        ),
        Disclosure(
            session=1,
            source="customer",
            action_type="OPEN_DEPOSIT_ACCOUNT",
            initiator="client",
            entity=NodeId(entity),
            relation="lastFour",
            value=value,
            node_id=NodeId(node),
        ),
    )


def test_both_folds_start_from_the_state_they_are_given() -> None:
    first = _opened("aaaaa", "bbbbb", LastFour("4471"))
    second = _opened("ccccc", "ddddd", LastFour("9012"))

    registry = fold_world(second, LOADED_PACK, fold_world(first, LOADED_PACK))
    graph = fold_trace(second, LOADED_PACK, fold_trace(first, LOADED_PACK))

    assert registry.ids() == {NodeId("aaaaa"), NodeId("ccccc")}
    assert {node.id for node in graph.entity_nodes()} == {
        NodeId("aaaaa"),
        NodeId("ccccc"),
    }
    assert registry == fold_world(first + second, LOADED_PACK)
    assert graph == fold_trace(first + second, LOADED_PACK)


def test_both_folds_start_empty_by_default() -> None:
    assert fold_world((), LOADED_PACK) == Registry()
    assert fold_trace((), LOADED_PACK) == Graph()


def test_the_folds_accept_records_the_predicate_would_refuse() -> None:
    bad_value = LastFour("44a1")
    records = _opened("aaaaa", "bbbbb", bad_value)

    registry = fold_world(records, LOADED_PACK)
    graph = fold_trace(records, LOADED_PACK)

    entry = registry.entry(NodeId("aaaaa"))
    assert entry is not None
    assert entry.values["lastFour"].value == bad_value
    assert {node.id for node in graph.entity_nodes()} == {NodeId("aaaaa")}
