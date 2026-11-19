import random
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from enum import Enum

from mbench.core.folds.registry import Entry, Registry, true_values
from mbench.core.legality.predicate import Reason, check
from mbench.core.legality.role_filters import Verdict, judge_gate
from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    ConflictingDoubleDisclosureCommand,
    EventCommand,
    InitCommand,
    MutateCommand,
)
from mbench.core.records.ids import NodeId
from mbench.core.values.protocol import ValueClass
from mbench.core.values.samplers import (
    Choice,
    MissingRead,
    Sampler,
    draw,
    draw_step,
)
from mbench.packs.spec import InitAction, LoadedPack, MutateAction

# An arbitrary bound: a clash is rare, so a few redraws normally clear it.
DEFAULT_REDRAW_LIMIT = 10

# Per relation, the values a caller tells the factory a draw must not return.
type AvoidList = Mapping[str, Collection[ValueClass]]


@dataclass(frozen=True)
class AgreeingDraft:
    """An agreeing double disclosure without its value."""

    session: int
    initiator: str
    action_type: str
    referent: NodeId
    sources: tuple[str, str]


@dataclass(frozen=True)
class ConflictDraft:
    """A conflicting double disclosure without its two values."""

    session: int
    initiator: str
    referent: NodeId
    relation: str
    # The first will state a, the second b.
    sources: tuple[str, str]


type Fillable = InitCommand | MutateCommand | AgreeingDraft | ConflictDraft


class FillReason(Enum):
    """Why a command could not be filled, a stable code."""

    NOTHING_LEFT_TO_DRAW = "nothing_left_to_draw"
    EXCLUSION_LIST_EMPTY = "exclusion_list_empty"
    NO_CURRENT_VALUE = "no_current_value"
    NO_VALUE_TO_READ = "no_value_to_read"
    # The refusals below are the ones that remained when the redraws ran out.
    IDENTIFIER_TAKEN = "identifier_taken"
    ANCHOR_SAME_ZONE = "anchor_same_zone"
    NO_WRITER = "no_writer"
    WRITER_GATE_FAILED = "writer_gate_failed"
    NO_CONTESTABLE_FRAMING = "no_contestable_framing"
    INITIATOR_NOT_SHARED = "initiator_not_shared"


# The refusals a new draw can clear, each with the reason the factory gives
# when the redraws run out. Any other refusal leaves the command to `decide`.
# The framing refusals arise only for a conflict, where another pair of
# values may have writers that share a framing.
_REDRAWN: Mapping[Reason, FillReason] = {
    Reason.IDENTIFIER_TAKEN: FillReason.IDENTIFIER_TAKEN,
    Reason.ANCHOR_SAME_ZONE: FillReason.ANCHOR_SAME_ZONE,
    Reason.NO_WRITER: FillReason.NO_WRITER,
    Reason.WRITER_GATE_FAILED: FillReason.WRITER_GATE_FAILED,
    Reason.NO_CONTESTABLE_FRAMING: FillReason.NO_CONTESTABLE_FRAMING,
    Reason.INITIATOR_NOT_SHARED: FillReason.INITIATOR_NOT_SHARED,
}


@dataclass(frozen=True)
class FillRefusal:
    """A command the factory could not fill, and why."""

    reason: FillReason


class _Refused(Exception):
    """A draw that cannot be made, ending the fill with the refusal."""

    def __init__(self, refusal: FillRefusal) -> None:
        """Carry the refusal the fill ends with."""

        super().__init__(refusal.reason.value)
        self.refusal = refusal


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
        self,
        command: Fillable,
        registry: Registry,
        avoid: AvoidList | None = None,
    ) -> EventCommand | FillRefusal:
        """The command with its values set, or why it cannot have them.

        A fill holds only at the registry it was drawn against, so the caller
        decides the command there, and a new placement needs a new fill.
        """

        avoid = avoid or {}

        if isinstance(command, ConflictDraft):
            return self._fill_conflict(command, registry, avoid)

        action = self._pack.action_types[command.action_type]

        if isinstance(command, InitCommand) and isinstance(action, InitAction):
            return self._fill_init(command, action, registry, avoid)
        if isinstance(command, MutateCommand | AgreeingDraft) and isinstance(
            action, MutateAction
        ):
            return self._fill_mutate(command, action, registry, avoid)

        # How to fill follows from the shape, so a command of the wrong shape
        # cannot be filled.
        raise TypeError(f"{type(command).__name__} cannot take {action.name}")

    def _redrawn(
        self, fill_once: Callable[[], EventCommand], registry: Registry
    ) -> EventCommand | FillRefusal:
        """Fill and check until no redraw could clear the refusal, if any."""

        clash: FillReason | None = None

        # Every value is drawn again, not just the one that clashed, since a
        # later sampler may have read it.
        for _ in range(self._redraw_limit + 1):
            try:
                filled = fill_once()
            except _Refused as refused:
                return refused.refusal

            refusal = check(filled, registry, self._pack)
            if refusal is None or refusal.reason not in _REDRAWN:
                return filled
            clash = _REDRAWN[refusal.reason]

        assert clash is not None
        return FillRefusal(clash)

    def _fill_init(
        self,
        command: InitCommand,
        action: InitAction,
        registry: Registry,
        avoid: AvoidList,
    ) -> EventCommand | FillRefusal:
        """The INIT with values that keep identifiers and anchors unique."""

        if command.writes:
            raise ValueError(f"{action.name} command is already filled")

        return self._redrawn(
            lambda: replace(command, writes=self._draw_writes(action, avoid)),
            registry,
        )

    def _draw_writes(
        self, action: InitAction, avoid: AvoidList
    ) -> dict[str, ValueClass]:
        """The INIT's fixed values, then its sampled ones in order."""

        # Fixed values come first, so any sampler may read them.
        writes: dict[str, ValueClass] = dict(action.fixes)

        for (init, relation), sampler in self._pack.init_samplers.items():
            if init != action.name:
                continue

            avoided = avoid.get(relation, ())
            value = draw(
                sampler,
                self._stream,
                pools=self._pack.pools,
                values=writes,
                exclude=avoided,
            )
            if value is None:
                raise _Refused(_nothing_left(avoided))
            writes[relation] = value

        return writes

    def _fill_mutate(
        self,
        command: MutateCommand | AgreeingDraft,
        action: MutateAction,
        registry: Registry,
        avoid: AvoidList,
    ) -> EventCommand | FillRefusal:
        """The MUTATE or agreeing pair with a step from the current value."""

        if isinstance(command, AgreeingDraft):
            # The pair names its value, which a status action fixes.
            if action.fixes is not None:
                raise TypeError(
                    f"a double disclosure cannot take status action"
                    f" {action.name}"
                )
        elif command.value is not None:
            raise ValueError(f"{action.name} command is already filled")
        elif action.fixes is not None:
            # A status action's value is the one it fixes, its command names
            # none.
            return command

        entry = registry.entry(command.referent)
        if entry is None or entry.type != action.referent_type:
            return FillRefusal(FillReason.NO_CURRENT_VALUE)

        stepper = self._stepper(entry, action.relation, avoid)
        if stepper is None:
            return FillRefusal(FillReason.NO_CURRENT_VALUE)

        def fill_once() -> EventCommand:
            """The command with one value stepped to."""

            value = stepper.step()
            if isinstance(command, MutateCommand):
                return replace(command, value=value)

            return AgreeingDoubleDisclosureCommand(
                session=command.session,
                initiator=command.initiator,
                action_type=command.action_type,
                referent=command.referent,
                value=value,
                sources=command.sources,
            )

        return self._redrawn(fill_once, registry)

    def _fill_conflict(
        self, draft: ConflictDraft, registry: Registry, avoid: AvoidList
    ) -> EventCommand | FillRefusal:
        """The conflict with two different values the pair could move to."""

        entry = registry.entry(draft.referent)
        if entry is None:
            return FillRefusal(FillReason.NO_CURRENT_VALUE)

        stepper = self._stepper(entry, draft.relation, avoid)
        if stepper is None:
            return FillRefusal(FillReason.NO_CURRENT_VALUE)

        def fill_once() -> EventCommand:
            """The conflict with two values stepped to, b avoiding a."""

            a = stepper.step()
            b = stepper.step(also_avoid=a)

            return ConflictingDoubleDisclosureCommand(
                session=draft.session,
                initiator=draft.initiator,
                referent=draft.referent,
                relation=draft.relation,
                a=a,
                b=b,
                sources=draft.sources,
            )

        return self._redrawn(fill_once, registry)

    def _stepper(
        self, entry: Entry, relation: str, avoid: AvoidList
    ) -> "_Stepper | None":
        """What draws the pair's next values, or None if it holds no truth."""

        # A conflict has no true value for a step to start from or a sampler
        # to read.
        values = true_values(entry)
        current = values.get(relation)
        if current is None:
            return None

        # A status moves by its status actions, not a step sampler: any of
        # them whose transition starts at the current status.
        sampler: Sampler[ValueClass]
        if relation == self._pack.entity_types[entry.type].status:
            sampler = Choice(_moves(entry, relation, self._pack))
        elif (entry.type, relation) in self._pack.step_samplers:
            sampler = self._pack.step_samplers[(entry.type, relation)]
        else:
            # Like a command of the wrong shape: only a pair some MUTATE
            # writes has a next value to draw.
            raise ValueError(f"{entry.type} has no step sampler for {relation}")

        return _Stepper(
            sampler,
            self._stream,
            self._pack,
            values,
            current,
            avoid.get(relation, ()),
        )


@dataclass(frozen=True)
class _Stepper:
    """Draws next values for one pair, from its current value."""

    sampler: Sampler[ValueClass]
    stream: random.Random
    pack: LoadedPack
    # The entity's true values, which the sampler may read.
    values: Mapping[str, ValueClass]
    current: ValueClass
    avoided: Collection[ValueClass]

    def step(self, also_avoid: ValueClass | None = None) -> ValueClass:
        """A value one step from the current, off the avoid-list."""

        exclude = {*self.avoided}
        if also_avoid is not None:
            exclude.add(also_avoid)

        # What an entity holds is the log's doing, not the pack's, so a value
        # the sampler cannot read refuses. At an INIT it is a pack mistake.
        try:
            value = draw_step(
                self.sampler,
                self.current,
                self.stream,
                pools=self.pack.pools,
                values=self.values,
                exclude=exclude,
            )
        except MissingRead:
            raise _Refused(FillRefusal(FillReason.NO_VALUE_TO_READ)) from None

        if value is None:
            raise _Refused(_nothing_left(self.avoided))

        return value


def _moves(
    entry: Entry, relation: str, pack: LoadedPack
) -> tuple[ValueClass, ...]:
    """The statuses the entity's status actions can move it to now."""

    moves: dict[ValueClass, None] = {}

    # In declaration order, so a seed draws the same moves on every run. A
    # status action's gate names the statuses it moves from.
    for action in pack.action_types.values():
        if (
            isinstance(action, MutateAction)
            and action.referent_type == entry.type
            and action.relation == relation
            and action.fixes is not None
            and judge_gate(entry, action.gate) is not Verdict.FAIL
        ):
            moves[action.fixes] = None

    return tuple(moves)


def _nothing_left(avoided: Collection[ValueClass]) -> FillRefusal:
    """The refusal of an empty draw, blaming the avoid-list if any."""

    reason = (
        FillReason.EXCLUSION_LIST_EMPTY
        if avoided
        else FillReason.NOTHING_LEFT_TO_DRAW
    )

    return FillRefusal(reason)
