from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum

from mbench.core.records.ids import NodeId
from mbench.core.records.log import Disclosure, Link, Record, freeze
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack


class EdgeKind(Enum):
    """What an edge joins: an entity to a value node or entity, or a session."""

    VALUE = "value"
    STRUCTURAL = "structural"
    OCCURRED_IN = "occurredIn"
    SAID_IN = "saidIn"


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
    """An edge, a value or structural edge is labelled with its relation."""

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
    # The later sessions that re-said each value node, for those that have any.
    _said_in: Mapping[NodeId, frozenset[int]] = field(
        default_factory=lambda: freeze({})
    )
    # Each link disclosed, by its INIT only: a link is never re-said.
    _links: Mapping[Pair, NodeId] = field(default_factory=lambda: freeze({}))

    def entity_nodes(self) -> frozenset[EntityNode]:
        """Every entity something was said about."""

        return frozenset(self._entity_nodes.values())

    def value_nodes(self) -> frozenset[ValueNode]:
        """Every value node."""

        return frozenset(self._value_nodes.values())

    def session_nodes(self) -> frozenset[int]:
        """The index of every session something entered or was re-said in."""

        return frozenset(self._occurred_in.values()).union(
            *self._said_in.values()
        )

    def update_chain(self, pair: Pair) -> tuple[ValueNode, ...]:
        """The pair's value nodes in session order, oldest first."""

        # Nodes of one session (a conflict's two halves) have no order of
        # their own, the id only makes the chain the same on every run.
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

    def mentions(self, node: NodeId) -> frozenset[int]:
        """The later sessions that re-said the value node."""

        return self._said_in.get(node, frozenset())

    def edges(self) -> frozenset[Edge]:
        """Every edge: value, structural, each `occurredIn`, each mention."""

        value_edges = {
            Edge(EdgeKind.VALUE, entity, node, relation)
            for (entity, relation), nodes in self._value_nodes_by_pair.items()
            for node in nodes
        }
        structural = {
            Edge(EdgeKind.STRUCTURAL, entity, target, relation)
            for (entity, relation), target in self._links.items()
        }
        occurred_in = {
            Edge(EdgeKind.OCCURRED_IN, node, session)
            for node, session in self._occurred_in.items()
        }
        said_in = {
            Edge(EdgeKind.SAID_IN, node, session)
            for node, sessions in self._said_in.items()
            for session in sessions
        }

        return frozenset(value_edges | structural | occurred_in | said_in)


def evolve_trace(
    graph: Graph, disclosure: Disclosure, pack: LoadedPack
) -> Graph:
    """The graph after one disclosure: a node, an edge, a mention or nothing."""

    pair = (disclosure.entity, disclosure.relation)
    if isinstance(disclosure.value, Link):
        # A link is disclosed once, by its INIT, so it never re-says one.
        graph = _with_entity(graph, disclosure, pack)
        return replace(
            graph,
            _links=freeze({**graph._links, pair: disclosure.value.target}),
        )

    restated = _restated(graph, disclosure)
    if restated is not None:
        return _mentioned(graph, restated, disclosure.session)

    graph = _with_entity(graph, disclosure, pack)
    nodes = graph._value_nodes_by_pair.get(pair, frozenset())
    node = ValueNode(disclosure.node_id, disclosure.value)

    return replace(
        graph,
        _occurred_in=freeze(
            {**graph._occurred_in, node.id: disclosure.session}
        ),
        _value_nodes=freeze({**graph._value_nodes, node.id: node}),
        _value_nodes_by_pair=freeze(
            {**graph._value_nodes_by_pair, pair: nodes | {node.id}}
        ),
    )


def _with_entity(
    graph: Graph, disclosure: Disclosure, pack: LoadedPack
) -> Graph:
    """The graph with the disclosure's entity node, entering in its session."""

    if disclosure.entity in graph._entity_nodes:
        return graph

    # A disclosure names no type, its ActionType knows the entity's. Only an
    # entity's first disclosure is read for it, since a later one may be
    # framed by an action type the pack does not hold (a READ).
    action = pack.action_types[disclosure.action_type]
    entity = EntityNode(disclosure.entity, action.referent_type)

    return replace(
        graph,
        _occurred_in=freeze(
            {**graph._occurred_in, entity.id: disclosure.session}
        ),
        _entity_nodes=freeze({**graph._entity_nodes, entity.id: entity}),
    )


def _restated(graph: Graph, disclosure: Disclosure) -> ValueNode | None:
    """The pair's latest value node that the disclosure re-says, if any."""

    # Every write changes its pair's value, and every disclosure states the
    # world, so a disclosure equal to the latest value can only re-say it.
    latest = graph.latest((disclosure.entity, disclosure.relation))

    return next(
        (node for node in latest if node.value == disclosure.value), None
    )


def _mentioned(graph: Graph, node: ValueNode, session: int) -> Graph:
    """The graph with the node re-said in the session, if that is later."""

    # Re-said in its own session, the node is the second half of an agreeing
    # double disclosure, or a READ beside the write: nothing new is said.
    # In an earlier session the node did not yet exist to be re-said.
    if session <= graph._occurred_in[node.id]:
        return graph

    said_in = graph._said_in.get(node.id, frozenset())

    return replace(
        graph, _said_in=freeze({**graph._said_in, node.id: said_in | {session}})
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
