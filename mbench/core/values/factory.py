import random
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum

from mbench.core.folds.registry import Entry, Registry
from mbench.core.legality.predicate import refuse_anchor_same_zone
from mbench.core.records.commands import InitCommand, MutateCommand
from mbench.core.values.contested import Contested, WorldValue
from mbench.core.values.protocol import UniquenessScope, ValueClass
from mbench.core.values.samplers import MissingRead, draw, draw_step
from mbench.packs.spec import InitAction, LoadedPack, MutateAction

type Fillable = InitCommand | MutateCommand

# An arbitrary bound: a clash is rare, so a few redraws normally clear it.
DEFAULT_REDRAW_LIMIT = 10


class FillReason(Enum):
    """Why a command could not be filled, a stable code."""

    NOTHING_LEFT_TO_DRAW = "nothing_left_to_draw"
    NO_CURRENT_VALUE = "no_current_value"
    NO_VALUE_TO_READ = "no_value_to_read"
    # The clash that remained when the redraws ran out.
    IDENTIFIER_TAKEN = "identifier_taken"
    ANCHOR_SAME_ZONE = "anchor_same_zone"


@dataclass(frozen=True)
class FillRefusal:
    """A command the factory could not fill, and why."""

    reason: FillReason


class Factory:
    """Fills the values of commands from one seeded stream."""

    def __init__(
        self,
        seed: int,
        pack: LoadedPack,
        redraw_limit: int = DEFAULT_REDRAW_LIMIT,
    ) -> None:
        """Start a stream of its own from the seed, over the pack."""

        if redraw_limit < 0:
            raise ValueError(f"redraw limit {redraw_limit} is negative")

        # A private stream, so allocating ids shifts no value.
        self._stream = random.Random(seed)
        self._pack = pack
        self._redraw_limit = redraw_limit

    def fill(
        self, command: Fillable, registry: Registry
    ) -> Fillable | FillRefusal:
        """The command with its values set, or why it cannot have them."""

        action = self._pack.action_types[command.action_type]

        if isinstance(command, InitCommand) and isinstance(action, InitAction):
            return self._fill_init(command, action, registry)
        if isinstance(command, MutateCommand) and isinstance(
            action, MutateAction
        ):
            return self._fill_mutate(command, action, registry)

        # The predicate raises the same for a command of the wrong shape.
        raise TypeError(f"{type(command).__name__} cannot take {action.name}")

    def _fill_init(
        self, command: InitCommand, action: InitAction, registry: Registry
    ) -> InitCommand | FillRefusal:
        """The INIT with values that keep identifiers and anchors unique."""

        if command.writes:
            raise ValueError(f"{action.name} command is already filled")

        taken = _taken_identifiers(action.referent_type, registry)
        clash = FillReason.IDENTIFIER_TAKEN

        # Every value is drawn again, not just the one that clashed, since a
        # later sampler may have read it.
        for _ in range(self._redraw_limit + 1):
            writes = self._draw_writes(action)
            if writes is None:
                return FillRefusal(FillReason.NOTHING_LEFT_TO_DRAW)

            filled = replace(command, writes=writes)
            if _repeats_identifier(writes, taken):
                clash = FillReason.IDENTIFIER_TAKEN
            elif refuse_anchor_same_zone(filled, registry, self._pack):
                clash = FillReason.ANCHOR_SAME_ZONE
            else:
                return filled

        return FillRefusal(clash)

    def _draw_writes(self, action: InitAction) -> dict[str, ValueClass] | None:
        """The INIT's fixed values, then its sampled ones in order."""

        # Fixed values come first, so any sampler may read them.
        writes: dict[str, ValueClass] = dict(action.fixes)

        for (init, relation), sampler in self._pack.init_samplers.items():
            if init != action.name:
                continue

            value = draw(
                sampler, self._stream, pools=self._pack.pools, values=writes
            )
            if value is None:
                return None
            writes[relation] = value

        return writes

    def _fill_mutate(
        self, command: MutateCommand, action: MutateAction, registry: Registry
    ) -> MutateCommand | FillRefusal:
        """The MUTATE with a step from its relation's current value."""

        if command.value is not None:
            raise ValueError(f"{action.name} command is already filled")

        # A status action's value is the one it fixes, its command names none.
        if action.fixes is not None:
            return command

        entry = registry.entry(command.referent)
        if entry is None or entry.type != action.referent_type:
            return FillRefusal(FillReason.NO_CURRENT_VALUE)

        values = _plain_values(entry)
        current = values.get(action.relation)
        if current is None:
            return FillRefusal(FillReason.NO_CURRENT_VALUE)

        sampler = self._pack.step_samplers[(entry.type, action.relation)]
        taken = _taken_identifiers(entry.type, registry)

        for _ in range(self._redraw_limit + 1):
            # What an entity holds is the log's doing, not the pack's, so a
            # value the sampler cannot read refuses. At an INIT it is a pack
            # mistake.
            try:
                value = draw_step(
                    sampler,
                    current,
                    self._stream,
                    pools=self._pack.pools,
                    values=values,
                )
            except MissingRead:
                return FillRefusal(FillReason.NO_VALUE_TO_READ)

            if value is None:
                return FillRefusal(FillReason.NOTHING_LEFT_TO_DRAW)

            if value not in taken:
                return replace(command, value=value)

        # An anchor is never rewritten, so only an identifier can clash here.
        return FillRefusal(FillReason.IDENTIFIER_TAKEN)


def _taken_identifiers(
    entity_type: str, registry: Registry
) -> frozenset[ValueClass]:
    """The identifiers a new value on an entity of the type must differ from."""

    taken: set[ValueClass] = set()

    # Terminal entities count, as the registry keeps them: a closed card's
    # number still names that card.
    for entry in registry.entries():
        for stamped in entry.values.values():
            for value in _held_values(stamped.value):
                if value.scope is UniquenessScope.SCENARIO or (
                    value.scope is UniquenessScope.TYPE
                    and entry.type == entity_type
                ):
                    taken.add(value)

    return frozenset(taken)


def _held_values(value: WorldValue) -> frozenset[ValueClass]:
    """The plain values a pair holds, both sides of a conflict included."""

    # Either side of a conflict may be what the entity is called.
    return value.members if isinstance(value, Contested) else frozenset({value})


def _repeats_identifier(
    writes: Mapping[str, ValueClass], taken: frozenset[ValueClass]
) -> bool:
    """Whether an identifier written is taken, or written twice."""

    identifiers = [
        value
        for value in writes.values()
        if value.scope is not UniquenessScope.NONE
    ]

    return len(set(identifiers)) < len(identifiers) or not taken.isdisjoint(
        identifiers
    )


def _plain_values(entry: Entry) -> dict[str, ValueClass]:
    """The entity's current values, without any contested one."""

    # A conflict has no true value for a step to start from or a sampler to
    # read.
    return {
        relation: stamped.value
        for relation, stamped in entry.values.items()
        if not isinstance(stamped.value, Contested)
    }
