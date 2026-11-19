from dataclasses import dataclass

from mbench.core.folds.registry import Entry, Registry, true_value
from mbench.core.legality._clauses import refuse_sealed
from mbench.core.legality._refusal import Reason, Refusal
from mbench.core.records.commands import ReadCommand
from mbench.core.records.ids import IdAllocator
from mbench.core.records.log import READ, Disclosure, Record
from mbench.core.values.protocol import ValueClass


@dataclass(frozen=True)
class Read:
    """A READ the check has passed, with the entity it states."""

    command: ReadCommand
    entry: Entry

    def records(self, allocator: IdAllocator) -> tuple[Record, ...]:
        """The READ's disclosures of the entity's current values."""

        # Each value is copied from the registry, so these disclosures always
        # pass `refuse_untrue_disclosure`, only a disclosure written by other
        # means, as in a stored log, can fail it.
        return tuple(
            Disclosure(
                session=self.command.session,
                source=self.command.source,
                action_type=READ,
                initiator=self.command.initiator,
                entity=self.command.entity,
                relation=relation,
                value=_readable(self.entry, relation),
                node_id=allocator.allocate(),
            )
            for relation in self.entry.values
        )


def checked(command: ReadCommand, registry: Registry) -> Refusal | Read:
    """The READ with its entity, unless that is missing or sealed."""

    entry = registry.entry(command.entity)
    if entry is None:
        return Refusal(Reason.REFERENT_MISSING)

    # A READ states every value of its entity, so one contested pair is enough.
    return refuse_sealed(entry, entry.values.keys()) or Read(command, entry)


def _readable(entry: Entry, relation: str) -> ValueClass:
    """The value a READ states, which a conflict, having no truth, is not."""

    # A READ of an entity holding a conflict is refused as sealed, so the
    # values it states are never contested.
    value = true_value(entry, relation)
    assert value is not None

    return value
