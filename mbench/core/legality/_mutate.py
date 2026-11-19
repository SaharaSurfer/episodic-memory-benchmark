from collections.abc import Mapping
from dataclasses import dataclass

from mbench.core.folds.registry import (
    Entry,
    Liveness,
    Registry,
    Stamped,
    liveness,
)
from mbench.core.legality._caller_bugs import wrong_shape
from mbench.core.legality._clauses import (
    current_values,
    passes,
    refuse_invalid_values,
    refuse_sealed,
    refuse_sealed_entity,
    refuse_second_write,
    refuse_unchanged_value,
)
from mbench.core.legality._disclosures import disclosure_source, disclosures
from mbench.core.legality._refusal import Reason, Refusal
from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    MutateCommand,
)
from mbench.core.records.ids import IdAllocator
from mbench.core.records.log import MutateEvent, Record
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack, MutateAction


@dataclass(frozen=True)
class Mutate:
    """A plain write of one value on a referent: a MUTATE or agreeing pair."""

    command: MutateCommand | AgreeingDoubleDisclosureCommand
    writes: Mapping[str, ValueClass]
    sources: tuple[str, ...]
    entry: Entry
    # The current stamped value of each pair it writes, if any.
    current: Mapping[str, Stamped]

    def records(self, allocator: IdAllocator) -> tuple[Record, ...]:
        """The MUTATE event, then one disclosure of its value per source."""

        event = MutateEvent(
            session=self.command.session,
            initiator=self.command.initiator,
            action_type=self.command.action_type,
            referent=self.command.referent,
            writes=self.writes,
        )

        return (
            event,
            *(
                disclosure
                for source in self.sources
                for disclosure in disclosures(
                    event, event.referent, self.writes, source, allocator
                )
            ),
        )


def checked(
    command: MutateCommand | AgreeingDoubleDisclosureCommand,
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | Mutate:
    """The plain write resolved, or the first clause that refuses it."""

    action = _mutate_action(command, pack)
    writes = {action.relation: _written_value(command, action)}

    sources: tuple[str, ...]
    if isinstance(command, AgreeingDoubleDisclosureCommand):
        sources = command.sources
    else:
        sources = (disclosure_source(command, pack),)

    mutate = _resolve_referent(command, action, writes, sources, registry, pack)
    if isinstance(mutate, Refusal):
        return mutate

    relations = pack.entity_types[action.referent_type].relations
    refusal = (
        refuse_second_write(command.session, mutate.current)
        or refuse_invalid_values(relations, writes.items())
        or refuse_sealed(mutate.entry, mutate.current.keys())
        or refuse_sealed_entity(mutate.entry, pack)
        or refuse_unchanged_value(writes, mutate.current)
    )

    return refusal or mutate


def _resolve_referent(
    command: MutateCommand | AgreeingDoubleDisclosureCommand,
    action: MutateAction,
    writes: Mapping[str, ValueClass],
    sources: tuple[str, ...],
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | Mutate:
    """Refuse a write on a missing, mistyped, gated-out or dead referent."""

    entry = registry.entry(command.referent)
    if entry is None:
        return Refusal(Reason.REFERENT_MISSING)
    if entry.type != action.referent_type:
        return Refusal(Reason.REFERENT_WRONG_TYPE)
    if not passes(entry, action.gate):
        return Refusal(Reason.GATE_FAILED)

    # A gate that reads the status has named the statuses it admits, a
    # terminal one included, so it, not liveness, decides. An undecided
    # status passes here and is refused as sealed: by `refuse_sealed` if the
    # command writes the status, else ENTITY_SEALED by `refuse_sealed_entity`.
    status = pack.entity_types[entry.type].status
    if status not in action.gate and liveness(entry, pack) is Liveness.TERMINAL:
        return Refusal(Reason.NOT_LIVE)

    return Mutate(
        command, writes, sources, entry, current_values(entry, writes)
    )


def _mutate_action(
    command: MutateCommand | AgreeingDoubleDisclosureCommand, pack: LoadedPack
) -> MutateAction:
    """The MUTATE ActionType the command names."""

    action = pack.action_types[command.action_type]
    if not isinstance(action, MutateAction):
        raise wrong_shape(command, action.name)

    return action


def _written_value(
    command: MutateCommand | AgreeingDoubleDisclosureCommand,
    action: MutateAction,
) -> ValueClass:
    """The value a MUTATE writes: its status action's, else the command's."""

    # Its value is always named, so it never leaves one for the action to fix.
    if (
        isinstance(command, AgreeingDoubleDisclosureCommand)
        and action.fixes is not None
    ):
        raise TypeError(
            f"a double disclosure cannot take status action {action.name}"
        )

    if action.fixes is not None and command.value is None:
        return action.fixes
    if action.fixes is None and command.value is not None:
        return command.value

    # Like a command of the wrong shape: a status action's value is fixed, and
    # any other MUTATE must name one.
    raise TypeError(f"{action.name} needs a value iff it fixes none")
