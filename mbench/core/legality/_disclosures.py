from collections.abc import Mapping

from mbench.core.records.commands import InitCommand, MutateCommand
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import Disclosure, Event, Link
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack


def disclosure_source(
    command: InitCommand | MutateCommand, pack: LoadedPack
) -> str:
    """The source of the event's disclosures, the named one if any."""

    if command.source is not None:
        return command.source

    return pack.default_sources[command.initiator]


def disclosures(
    event: Event,
    entity: NodeId,
    stated: Mapping[str, ValueClass | Link],
    source: str,
    allocator: IdAllocator,
) -> tuple[Disclosure, ...]:
    """One disclosure per value or link the event writes, framed by it."""

    return tuple(
        Disclosure(
            session=event.session,
            source=source,
            action_type=event.action_type,
            initiator=event.initiator,
            entity=entity,
            relation=relation,
            value=value,
            node_id=allocator.allocate(),
        )
        for relation, value in stated.items()
    )
