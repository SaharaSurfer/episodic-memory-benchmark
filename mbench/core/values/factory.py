import random
from dataclasses import dataclass, replace
from enum import Enum

from mbench.core.folds.registry import Entry, Registry
from mbench.core.records.commands import InitCommand, MutateCommand
from mbench.core.values.contested import Contested
from mbench.core.values.protocol import ValueClass
from mbench.core.values.samplers import MissingRead, draw, draw_step
from mbench.packs.spec import InitAction, LoadedPack, MutateAction

type Fillable = InitCommand | MutateCommand


class FillReason(Enum):
    """Why a command could not be filled, a stable code."""

    NOTHING_LEFT_TO_DRAW = "nothing_left_to_draw"
    NO_CURRENT_VALUE = "no_current_value"
    NO_VALUE_TO_READ = "no_value_to_read"


@dataclass(frozen=True)
class FillRefusal:
    """A command the factory could not fill, and why."""

    reason: FillReason


class Factory:
    """Fills the values of commands from one seeded stream."""

    def __init__(self, seed: int, pack: LoadedPack) -> None:
        """Start a stream of its own from the seed, over the pack."""

        # A private stream, so allocating ids shifts no value.
        self._stream = random.Random(seed)
        self._pack = pack

    def fill(
        self, command: Fillable, registry: Registry
    ) -> Fillable | FillRefusal:
        """The command with its values set, or why it cannot have them."""

        action = self._pack.action_types[command.action_type]

        if isinstance(command, InitCommand) and isinstance(action, InitAction):
            return self._fill_init(command, action)
        if isinstance(command, MutateCommand) and isinstance(
            action, MutateAction
        ):
            return self._fill_mutate(command, action, registry)

        # The predicate raises the same for a command of the wrong shape.
        raise TypeError(f"{type(command).__name__} cannot take {action.name}")

    def _fill_init(
        self, command: InitCommand, action: InitAction
    ) -> InitCommand | FillRefusal:
        """The INIT with its fixed values, then its sampled ones in order."""

        if command.writes:
            raise ValueError(f"{action.name} command is already filled")

        # Fixed values come first, so any sampler may read them.
        writes: dict[str, ValueClass] = dict(action.fixes)

        for (init, relation), sampler in self._pack.init_samplers.items():
            if init != action.name:
                continue

            value = draw(
                sampler, self._stream, pools=self._pack.pools, values=writes
            )
            if value is None:
                return FillRefusal(FillReason.NOTHING_LEFT_TO_DRAW)
            writes[relation] = value

        return replace(command, writes=writes)

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

        # What an entity holds is the log's doing, not the pack's, so a value
        # the sampler cannot read refuses. At an INIT it is a pack mistake.
        try:
            value = draw_step(
                self._pack.step_samplers[(entry.type, action.relation)],
                current,
                self._stream,
                pools=self._pack.pools,
                values=values,
            )
        except MissingRead:
            return FillRefusal(FillReason.NO_VALUE_TO_READ)

        if value is None:
            return FillRefusal(FillReason.NOTHING_LEFT_TO_DRAW)

        return replace(command, value=value)


def _plain_values(entry: Entry) -> dict[str, ValueClass]:
    """The entity's current values, without any contested one."""

    # A conflict has no true value for a step to start from or a sampler to
    # read.
    return {
        relation: stamped.value
        for relation, stamped in entry.values.items()
        if not isinstance(stamped.value, Contested)
    }
