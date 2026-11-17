from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum

from mbench.core.records.ids import NodeId
from mbench.core.records.log import Disclosure, Record, freeze
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack


class EdgeKind(Enum):
    """What an edge joins: an entity to a value node, or a node to a session."""

    VALUE = "value"
    OCCURRED_IN = "occurredIn"


@dataclass(frozen=True)
class EntityNode:
    """A thing with a history: its id and its type, nothing else."""

    id: NodeId
    type: str


@dataclass(frozen=True)
class ValueNode:
    """One version of one fact: a value at one write."""

    id: NodeId
    value: ValueClass


@dataclass(frozen=True)
class Edge:
    """An edge, a value edge is labelled with its relation."""

    kind: EdgeKind
    source: NodeId
    target: NodeId | int
    relation: str | None = None


type Pair = tuple[NodeId, str]


@dataclass(frozen=True)
class Graph:
    """The knowledge trace: every node something disclosed, and its edges."""

    # The session each entity node and value node entered the trace in.
    _occurred_in: Mapping[NodeId, int] = field(
        default_factory=lambda: freeze({})
    )
    _entity_nodes: Mapping[NodeId, EntityNode] = field(
        default_factory=lambda: freeze({})
    )
    _value_nodes: Mapping[NodeId, ValueNode] = field(
        default_factory=lambda: freeze({})
    )
    # Each pair's value nodes, unordered: version order is read from the
    # sessions they occurred in, so storing an order could only contradict it.
    _value_nodes_by_pair: Mapping[Pair, frozenset[NodeId]] = field(
        default_factory=lambda: freeze({})
    )

    def entity_nodes(self) -> frozenset[EntityNode]:
        """Every entity something was said about."""

        return frozenset(self._entity_nodes.values())

    def value_nodes(self) -> frozenset[ValueNode]:
        """Every value node."""

        return frozenset(self._value_nodes.values())

    def session_nodes(self) -> frozenset[int]:
        """The index of every session something entered the trace in."""

        return frozenset(self._occurred_in.values())

    def update_chain(self, pair: Pair) -> tuple[ValueNode, ...]:
        """The pair's value nodes in session order, oldest first."""

        # Nodes of one session (a conflict's two halves) have no order of
        # their own; the id only makes the chain the same on every run.
        nodes = sorted(
            self._value_nodes_by_pair.get(pair, ()),
            key=lambda node: (self._occurred_in[node], node),
        )

        return tuple(self._value_nodes[node] for node in nodes)

    def versions(self, pair: Pair) -> int:
        """How many writes the pair has had, one value node each."""

        return len(self._value_nodes_by_pair.get(pair, ()))

    def latest(self, pair: Pair) -> frozenset[ValueNode]:
        """The pair's value nodes of its latest session, two for a conflict."""

        nodes = self._value_nodes_by_pair.get(pair, frozenset())
        if not nodes:
            return frozenset()

        last = max(self._occurred_in[node] for node in nodes)

        return frozenset(
            self._value_nodes[node]
            for node in nodes
            if self._occurred_in[node] == last
        )

    def edges(self) -> frozenset[Edge]:
        """Every edge: each value edge and each node's `occurredIn`."""

        value_edges = {
            Edge(EdgeKind.VALUE, entity, node, relation)
            for (entity, relation), nodes in self._value_nodes_by_pair.items()
            for node in nodes
        }
        occurred_in = {
            Edge(EdgeKind.OCCURRED_IN, node, session)
            for node, session in self._occurred_in.items()
        }

        return frozenset(value_edges | occurred_in)


def evolve_trace(
    graph: Graph, disclosure: Disclosure, pack: LoadedPack
) -> Graph:
    """The graph after one disclosure."""

    entities = graph._entity_nodes
    if disclosure.entity not in entities:
        # A disclosure names no type, its ActionType knows the entity's. Only
        # an entity's first disclosure is read for it, since a later one may
        # be framed by an action type the pack does not hold (a READ).
        action = pack.action_types[disclosure.action_type]
        entity = EntityNode(disclosure.entity, action.referent_type)
        entities = {**entities, entity.id: entity}

    pair = (disclosure.entity, disclosure.relation)
    nodes = graph._value_nodes_by_pair.get(pair, frozenset())
    node = ValueNode(disclosure.node_id, disclosure.value)
    occurred_in = {disclosure.node_id: disclosure.session}
    occurred_in.setdefault(disclosure.entity, disclosure.session)

    # The graph's own entries come last: a node already in the trace keeps
    # the session it entered in, so only new nodes take this one.
    return Graph(
        _occurred_in=freeze({**occurred_in, **graph._occurred_in}),
        _entity_nodes=freeze(entities),
        _value_nodes=freeze({**graph._value_nodes, node.id: node}),
        _value_nodes_by_pair=freeze(
            {**graph._value_nodes_by_pair, pair: nodes | {node.id}}
        ),
    )


def fold_trace(
    records: Iterable[Record],
    pack: LoadedPack,
    start: Graph | None = None,
) -> Graph:
    """The graph of the log's disclosures, from the given or empty state."""

    graph = Graph() if start is None else start

    for record in records:
        if isinstance(record, Disclosure):
            graph = evolve_trace(graph, record, pack)

    return graph
