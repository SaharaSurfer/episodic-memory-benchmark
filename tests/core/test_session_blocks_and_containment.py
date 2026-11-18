from collections import Counter
from collections.abc import Callable
from decimal import Decimal

import pytest

from mbench.core.folds.graph import (
    Edge,
    EdgeKind,
    EntityNode,
    Graph,
    SessionBlock,
    ValueNode,
    fold_trace,
)
from mbench.core.records.commands import Command
from mbench.core.records.ids import NodeId
from mbench.core.records.log import Link
from mbench.core.values.protocol import ValueClass
from tests.core.records.handmade import OPEN_ACCOUNT, disclosure_of
from tests.core.world import (
    CARD_LINK,
    FEE,
    ISSUED_IN,
    LAST_FOURS,
    OPENED_IN,
    WRITES,
    World,
    agree,
    contest,
    disclosures_in,
    issue,
    open_account,
    read,
    reprice,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import InterestRate, LastFour, MonetaryAmount

RATE = "hasInterestRate"
STATED_RATE = InterestRate(Decimal("3.90"))


def _busy_graph() -> Graph:
    world = World()
    account = world.open()
    world.issue_card(account)
    world.accept(reprice(account, 3, "3.90"))
    world.accept(read(account, 4))
    world.accept(agree(account, 5, "3.80"))
    world.accept(read(account, 6))
    world.accept(contest(account, 7, "3.70", "3.60"))

    return world.graph


def _blocks(graph: Graph) -> list[SessionBlock]:
    return [graph.block(session) for session in sorted(graph.session_nodes())]


def _block_edges(block: SessionBlock) -> frozenset[Edge]:
    created = block.entity_nodes | block.value_nodes
    occurred_in = {
        Edge(EdgeKind.OCCURRED_IN, node.id, block.session) for node in created
    }
    said_in = {
        Edge(EdgeKind.SAID_IN, node.id, block.session)
        for node in block.mentions
    }

    return block.value_edges | block.structural_edges | occurred_in | said_in


def _graph_stating(
    relation: str = RATE,
    value: ValueClass | Link = STATED_RATE,
    session: int = OPENED_IN,
) -> Graph:
    disclosure = disclosure_of(
        NodeId("aaaaa"),
        relation,
        value,
        session=session,
        action_type=OPEN_ACCOUNT,
    )

    return fold_trace([disclosure], LOADED_PACK)


def test_an_opening_block_holds_everything_the_opening_created() -> None:
    world = World()
    account = world.open()
    opening = disclosures_in(world.records)

    block = world.graph.block(OPENED_IN)

    assert block.session == OPENED_IN
    assert block.entity_nodes == {EntityNode(account, "DEPOSIT_ACCOUNT")}
    assert block.value_nodes == {
        ValueNode(d.node_id, WRITES[d.relation]) for d in opening
    }
    assert block.value_edges == {
        Edge(EdgeKind.VALUE, account, d.node_id, d.relation) for d in opening
    }
    assert block.structural_edges == frozenset()
    assert block.mentions == frozenset()


def test_a_value_edge_is_in_the_block_of_its_value_node() -> None:
    world = World()
    account = world.open()
    [write] = disclosures_in(world.accept(reprice(account, 3, "3.90")))
    edge = Edge(EdgeKind.VALUE, account, write.node_id, write.relation)

    graph = world.graph

    assert graph.block(3).value_edges == {edge}
    assert edge not in graph.block(OPENED_IN).value_edges


def test_a_link_is_in_the_block_of_the_entity_it_goes_from() -> None:
    world = World()
    account = world.open()
    card = world.issue_card(account)

    graph = world.graph

    assert graph.block(ISSUED_IN).structural_edges == {
        Edge(EdgeKind.STRUCTURAL, card, account, CARD_LINK)
    }
    assert graph.block(OPENED_IN).structural_edges == frozenset()


def test_a_read_block_holds_only_mentions_of_earlier_value_nodes() -> None:
    world = World()
    account = world.open()
    opening = disclosures_in(world.records)
    world.accept(read(account, 3))

    block = world.graph.block(3)

    assert block.mentions == {
        ValueNode(d.node_id, WRITES[d.relation]) for d in opening
    }
    assert block.entity_nodes == frozenset()
    assert block.value_nodes == frozenset()
    assert block.value_edges == frozenset()
    assert block.structural_edges == frozenset()


def test_a_block_holds_both_what_its_session_wrote_and_mentioned() -> None:
    world = World()
    account = world.open()
    opening = disclosures_in(world.records)
    world.accept(read(account, 3))
    [write] = disclosures_in(world.accept(reprice(account, 3, "3.90")))

    block = world.graph.block(3)

    assert block.value_nodes == {ValueNode(write.node_id, STATED_RATE)}
    assert block.mentions == {
        ValueNode(d.node_id, WRITES[d.relation]) for d in opening
    }


def test_a_session_that_added_nothing_has_an_empty_block() -> None:
    world = World()
    world.open()

    block = world.graph.block(9)

    assert block == SessionBlock(
        session=9,
        entity_nodes=frozenset(),
        value_nodes=frozenset(),
        value_edges=frozenset(),
        structural_edges=frozenset(),
        mentions=frozenset(),
    )


def test_the_blocks_together_are_the_whole_graph() -> None:
    graph = _busy_graph()
    blocks = _blocks(graph)

    assert graph.session_nodes() == set(range(1, 8))
    assert {n for b in blocks for n in b.entity_nodes} == graph.entity_nodes()
    assert {n for b in blocks for n in b.value_nodes} == graph.value_nodes()
    assert {e for b in blocks for e in _block_edges(b)} == graph.edges()


def test_no_created_element_is_in_two_blocks() -> None:
    blocks = _blocks(_busy_graph())

    created = Counter(
        element
        for block in blocks
        for element in (
            *block.entity_nodes,
            *block.value_nodes,
            *block.value_edges,
            *block.structural_edges,
        )
    )

    assert set(created.values()) == {1}


def test_every_mention_names_a_value_node_of_an_earlier_block() -> None:
    blocks = _blocks(_busy_graph())
    created_in = {
        node: block.session for block in blocks for node in block.value_nodes
    }

    mentions = [(node, b.session) for b in blocks for node in b.mentions]

    assert mentions
    assert all(created_in[node] < said for node, said in mentions)


def test_a_graph_contains_itself() -> None:
    graph = _busy_graph()

    assert graph.contains(graph)


def test_a_nonempty_graph_contains_the_empty_one_and_not_the_reverse() -> None:
    graph = _busy_graph()

    assert graph.contains(Graph())
    assert not Graph().contains(graph)


def test_a_graph_lacking_only_an_edge_does_not_contain_the_one_with_it() -> (
    None
):
    world = World()
    account = world.open()
    without = world.graph

    world.accept(read(account, 2))

    assert world.graph.value_nodes() == without.value_nodes()
    assert world.graph.entity_nodes() == without.entity_nodes()
    assert not without.contains(world.graph)


def test_containment_compares_value_nodes_by_id_alone() -> None:
    other_rate = InterestRate(Decimal("3.80"))

    assert _graph_stating().contains(_graph_stating(value=other_rate))


def test_the_same_node_in_another_session_is_not_contained() -> None:
    other = _graph_stating(session=ISSUED_IN)

    assert not _graph_stating().contains(other)


def test_the_same_node_under_another_relation_is_not_contained() -> None:
    other = _graph_stating(FEE, MonetaryAmount(Decimal("5")))

    assert not _graph_stating().contains(other)


def test_the_same_link_to_another_target_is_not_contained() -> None:
    graph = _graph_stating(CARD_LINK, Link(NodeId("bbbbb")))
    other = _graph_stating(CARD_LINK, Link(NodeId("ccccc")))

    assert not graph.contains(other)


@pytest.mark.parametrize(
    "appended",
    [
        lambda _: open_account(4, lastFour=LastFour(LAST_FOURS[1])),
        lambda account: issue(account, 4),
        lambda account: reprice(account, 4, "3.70"),
        lambda account: read(account, 4),
    ],
    ids=["new entity", "new link", "new version", "read"],
)
def test_appending_an_accepted_command_strictly_grows_the_graph(
    appended: Callable[[NodeId], Command],
) -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 3, "3.90"))
    earlier = world.graph

    world.accept(appended(account))

    assert world.graph.contains(earlier)
    assert not earlier.contains(world.graph)
