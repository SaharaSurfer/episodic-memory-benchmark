from collections.abc import Mapping

from mbench.core.records.ids import NodeId
from mbench.core.records.log import READ, Disclosure, InitEvent, Link
from mbench.core.values.protocol import ValueClass

OPEN_ACCOUNT = "OPEN_DEPOSIT_ACCOUNT"

# The node of a disclosure written by hand, which no test looks up by id.
STATED_NODE = NodeId("yyyyy")


def opened_event(
    new_id: NodeId, writes: Mapping[str, ValueClass], session: int = 1
) -> InitEvent:
    """An event opening an account, written by hand."""

    return InitEvent(
        session=session,
        initiator="CLIENT",
        action_type=OPEN_ACCOUNT,
        new_id=new_id,
        writes=writes,
    )


def disclosure_of(
    entity: NodeId,
    relation: str,
    value: ValueClass | Link,
    *,
    session: int = 3,
    source: str = "operator",
    action_type: str = READ,
    node_id: NodeId = STATED_NODE,
) -> Disclosure:
    """A disclosure written by hand, by default a READ's."""

    return Disclosure(
        session=session,
        source=source,
        action_type=action_type,
        initiator="CLIENT",
        entity=entity,
        relation=relation,
        value=value,
        node_id=node_id,
    )
