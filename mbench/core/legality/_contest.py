from collections.abc import Mapping
from dataclasses import dataclass

from mbench.core.folds.registry import (
    Entry,
    Liveness,
    Registry,
    liveness,
    true_value,
)
from mbench.core.legality._clauses import (
    current_values,
    passes,
    refuse_invalid_values,
    refuse_sealed,
    refuse_sealed_entity,
    refuse_second_write,
    refuse_unchanged_value,
)
from mbench.core.legality._refusal import Reason, Refusal
from mbench.core.records.commands import ConflictingDoubleDisclosureCommand
from mbench.core.records.ids import IdAllocator
from mbench.core.records.log import CONTEST, Disclosure, MutateEvent, Record
from mbench.core.values.contested import Contested, WorldValue
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack, MutateAction, SourceKind


@dataclass(frozen=True)
class Contest:
    """A contested write, with the ActionType that writes each of its values."""

    command: ConflictingDoubleDisclosureCommand
    writes: Mapping[str, WorldValue]
    writers: tuple[MutateAction, MutateAction]

    def records(self, allocator: IdAllocator) -> tuple[Record, ...]:
        """The CONTEST event, then each source's disclosure of its own value."""

        command = self.command
        event = MutateEvent(
            session=command.session,
            initiator=command.initiator,
            action_type=CONTEST,
            referent=command.referent,
            writes=self.writes,
        )

        return (
            event,
            *(
                Disclosure(
                    session=event.session,
                    source=source,
                    action_type=writer.name,
                    initiator=event.initiator,
                    entity=event.referent,
                    relation=command.relation,
                    value=value,
                    node_id=allocator.allocate(),
                )
                for source, value, writer in zip(
                    command.sources,
                    (command.a, command.b),
                    self.writers,
                    strict=True,
                )
            ),
        )


def checked(
    command: ConflictingDoubleDisclosureCommand,
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | Contest:
    """The contested write resolved, or the first clause that refuses it."""

    writes = {command.relation: Contested(command.a, command.b)}

    entry = _contested_referent(command, registry, pack)
    if isinstance(entry, Refusal):
        return entry

    current = current_values(entry, writes)
    relations = pack.entity_types[entry.type].relations
    stated = ((command.relation, command.a), (command.relation, command.b))

    # Sealing runs just before the writers: it refuses exactly a pair already
    # contested, which no writer can write from, so the writers never see one
    # and either order gives every command the same refusal.
    refusal = (
        refuse_second_write(command.session, current)
        or refuse_invalid_values(relations, stated)
        or _refuse_contest_sources(command, pack)
        or _refuse_contest_values(command, entry)
        or refuse_sealed(entry, current.keys())
    )
    if refusal is not None:
        return refusal

    writers = _contest_writers(command, entry, pack)
    if isinstance(writers, Refusal):
        return writers

    refusal = refuse_sealed_entity(entry, pack) or refuse_unchanged_value(
        writes, current
    )

    return refusal or Contest(command, writes, writers)


def _contested_referent(
    command: ConflictingDoubleDisclosureCommand,
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | Entry:
    """The contested pair's entity, unless it is missing or dead."""

    entry = registry.entry(command.referent)
    if entry is None:
        return Refusal(Reason.REFERENT_MISSING)

    # It names no ActionType, so it has no referent type or gate of its own.
    # An undecided status passes here and is refused as sealed: by
    # `refuse_sealed` if the command contests the status, else ENTITY_SEALED
    # by `refuse_sealed_entity`.
    if liveness(entry, pack) is Liveness.TERMINAL:
        return Refusal(Reason.NOT_LIVE)

    return entry


def _refuse_contest_sources(
    command: ConflictingDoubleDisclosureCommand, pack: LoadedPack
) -> Refusal | None:
    """Refuse sources of unequal authority, or one speaker named twice."""

    first, second = (pack.sources[source] for source in command.sources)

    if first.authority != second.authority:
        return Refusal(Reason.UNEQUAL_AUTHORITY)

    # Two letters are two messages, one person giving two figures is a
    # self-correction.
    if first.id == second.id and first.kind is SourceKind.SPEAKER:
        return Refusal(Reason.SPEAKER_TWICE)

    return None


def _refuse_contest_values(
    command: ConflictingDoubleDisclosureCommand, entry: Entry
) -> Refusal | None:
    """Refuse two equal values, or one the pair already holds."""

    if command.a == command.b:
        return Refusal(Reason.CONTESTED_VALUES_EQUAL)

    # Only the current value: the registry keeps no earlier versions, so
    # whoever draws the two values must avoid those.
    current = entry.values.get(command.relation)
    if current is not None and current.value in (command.a, command.b):
        return Refusal(Reason.CONTESTED_VALUE_IS_CURRENT)

    return None


def _contest_writers(
    command: ConflictingDoubleDisclosureCommand,
    entry: Entry,
    pack: LoadedPack,
) -> Refusal | tuple[MutateAction, MutateAction]:
    """The unstated, co-initiated ActionTypes that write each value, if any."""

    writers = []
    for value in (command.a, command.b):
        writer = _find_writer(entry, command.relation, value, pack)
        if writer is None:
            return Refusal(Reason.NO_WRITER)
        if not passes(entry, writer.gate):
            return Refusal(Reason.WRITER_GATE_FAILED)
        if not pack.passes_owner_rule(writer.name):
            return Refusal(Reason.NO_CONTESTABLE_FRAMING)
        writers.append(writer)

    # The command names the initiator, since two framings may share several.
    first, second = writers
    if command.initiator not in pack.shared_initiators(first.name, second.name):
        return Refusal(Reason.INITIATOR_NOT_SHARED)

    return first, second


def _find_writer(
    entry: Entry, relation: str, value: ValueClass, pack: LoadedPack
) -> MutateAction | None:
    """The ActionType that would write the value over the pair's current."""

    current = true_value(entry, relation)
    if current is None:
        return None

    return pack.action_for(entry.type, relation, (current, value))
