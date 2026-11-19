import random
from collections.abc import Collection, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum

from mbench.core.folds.registry import Entry, Registry
from mbench.core.legality.predicate import Refusal
from mbench.core.log_builder import DryRun, LogBuilder
from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    Command,
    ConflictingDoubleDisclosureCommand,
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.core.records.log import AcceptedCommand, Log
from mbench.core.values.factory import (
    AgreeingDraft,
    ConflictDraft,
    Factory,
    FillRefusal,
)
from mbench.packs.spec import Framing, InitAction, LoadedPack, MutateAction
from tests.testpack.pack import LOADED_PACK

# How often a draw opens a later session, so pairs can be written again.
NEXT_SESSION_CHANCE = 0.3
# How often an INIT's link names a role filter, and a command its source.
FILTER_CHANCE = 0.3
NAMED_SOURCE_CHANCE = 0.5


class Shape(Enum):
    """The kinds of command the driver draws."""

    INIT = "init"
    MUTATE = "mutate"
    STATUS_MOVE = "status_move"
    READ = "read"
    AGREEING = "agreeing"
    CONFLICTING = "conflicting"


type Outcome = AcceptedCommand | Refusal | FillRefusal


@dataclass(frozen=True)
class GeneratedLog:
    """A generated log, and the registry its builder folded step by step."""

    log: Log
    registry: Registry


def generate_log(
    seed: int, steps: int, pack: LoadedPack = LOADED_PACK
) -> GeneratedLog:
    """A random legal log from the given number of draws, kept if accepted."""

    stream = random.Random(seed)
    factory = Factory(stream.getrandbits(32), pack)
    builder = LogBuilder(pack, id_seed=stream.getrandbits(32))
    session = 1

    for _ in range(steps):
        # Sessions only move forward: the builder raises on an earlier one.
        if stream.random() < NEXT_SESSION_CHANCE:
            session += 1

        run = builder.dry_run()
        outcome = draw_and_decide(run, session, stream, factory, pack)
        if isinstance(outcome, AcceptedCommand):
            builder.commit(run)

    return GeneratedLog(builder.log, builder.registry)


def canonical(value: object) -> str:
    """The value written out the same way under any hash seed.

    Sets and mappings are written sorted, so two equal logs from processes
    that hash strings differently are written alike.
    """

    if isinstance(value, frozenset | set):
        return "{" + ", ".join(sorted(canonical(item) for item in value)) + "}"
    if isinstance(value, Mapping):
        items = sorted(
            f"{canonical(key)}: {canonical(item)}"
            for key, item in value.items()
        )
        return "{" + ", ".join(items) + "}"
    if isinstance(value, tuple | list):
        return "(" + ", ".join(canonical(item) for item in value) + ")"
    if is_dataclass(value) and not isinstance(value, type):
        written = ", ".join(
            f"{field.name}={canonical(getattr(value, field.name))}"
            for field in fields(value)
        )
        return f"{type(value).__name__}({written})"

    return repr(value)


def shape_of(command: Command, pack: LoadedPack) -> Shape:
    """The kind of command it is, a status move told from other MUTATEs."""

    match command:
        case InitCommand():
            return Shape.INIT
        case MutateCommand():
            action = pack.action_types[command.action_type]
            assert isinstance(action, MutateAction)
            return Shape.MUTATE if action.fixes is None else Shape.STATUS_MOVE
        case ReadCommand():
            return Shape.READ
        case AgreeingDoubleDisclosureCommand():
            return Shape.AGREEING
        case ConflictingDoubleDisclosureCommand():
            return Shape.CONFLICTING


def draw_and_decide(
    run: DryRun,
    session: int,
    stream: random.Random,
    factory: Factory,
    pack: LoadedPack,
) -> Outcome | None:
    """One drawn command decided in the run, or None if none could be drawn."""

    registry = run.registry
    shape = stream.choice(list(Shape))

    match shape:
        case Shape.INIT:
            init = _draw_init(session, stream, registry, pack)
            return None if init is None else run.fill_and_decide(init, factory)
        case Shape.MUTATE | Shape.STATUS_MOVE:
            mutate = _draw_mutate(
                session, stream, registry, pack, shape is Shape.STATUS_MOVE
            )
            if mutate is None:
                return None
            return run.fill_and_decide(mutate, factory)
        case Shape.READ:
            read = _draw_read(session, stream, registry, pack)
            return None if read is None else run.decide(read)
        case Shape.AGREEING:
            agreeing = _draw_agreeing(session, stream, registry, pack)
            if agreeing is None:
                return None
            return run.fill_and_decide(agreeing, factory)
        case Shape.CONFLICTING:
            contest = _draw_contest(session, stream, registry, pack)
            if contest is None:
                return None
            return run.fill_and_decide(contest, factory)


def _draw_init(
    session: int, stream: random.Random, registry: Registry, pack: LoadedPack
) -> InitCommand | None:
    """An unfilled INIT, each link to an entity of a type it may point at."""

    # Only an INIT with something to link to, so an early draw is not wasted.
    actions = [
        action
        for action in _actions(pack, InitAction)
        if all(
            _of_types(registry, _link_types(action, link, pack))
            for link in action.links
        )
    ]
    if not actions:
        return None

    action = stream.choice(actions)
    links = {}
    filters = {}

    for link in sorted(action.links):
        target = stream.choice(
            _of_types(registry, _link_types(action, link, pack))
        )
        links[link] = target.id

        # A filter relating two roles cannot be stored, so none is drawn.
        usable = sorted(
            role_filter.name
            for role_filter in pack.role_filters.values()
            if role_filter.of is None
            and role_filter.entity_type in (None, target.type)
        )
        if usable and stream.random() < FILTER_CHANCE:
            filters[link] = stream.choice(usable)

    framing = _framing(stream, action.name, pack)

    return InitCommand(
        session=session,
        initiator=framing.initiator,
        action_type=action.name,
        writes={},
        source=_source(stream, framing),
        links=links,
        filters=filters,
    )


def _draw_mutate(
    session: int,
    stream: random.Random,
    registry: Registry,
    pack: LoadedPack,
    status: bool,
) -> MutateCommand | None:
    """An unfilled MUTATE on an entity of its type, a status move or not."""

    actions = [
        action
        for action in _actions(pack, MutateAction)
        if (action.fixes is not None) is status
        and _of_types(registry, {action.referent_type})
    ]
    if not actions:
        return None

    action = stream.choice(actions)
    referent = stream.choice(_of_types(registry, {action.referent_type}))

    framing = _framing(stream, action.name, pack)

    return MutateCommand(
        session=session,
        initiator=framing.initiator,
        action_type=action.name,
        referent=referent.id,
        source=_source(stream, framing),
    )


def _draw_read(
    session: int, stream: random.Random, registry: Registry, pack: LoadedPack
) -> ReadCommand | None:
    """A READ of any entity, by any source for any initiator."""

    entity = _pick(stream, registry, pack.entity_types.keys())
    if entity is None:
        return None

    return ReadCommand(
        session=session,
        initiator=stream.choice(sorted(pack.actors)),
        source=stream.choice(sorted(pack.sources)),
        entity=entity.id,
    )


def _draw_agreeing(
    session: int, stream: random.Random, registry: Registry, pack: LoadedPack
) -> AgreeingDraft | None:
    """A draft of a value step, stated by two different sources."""

    mutate = _draw_mutate(session, stream, registry, pack, status=False)
    if mutate is None:
        return None

    first, second = stream.sample(sorted(pack.sources), 2)

    return AgreeingDraft(
        session=session,
        initiator=mutate.initiator,
        action_type=mutate.action_type,
        referent=mutate.referent,
        sources=(first, second),
    )


def _draw_contest(
    session: int, stream: random.Random, registry: Registry, pack: LoadedPack
) -> ConflictDraft | None:
    """A draft of two values for one pair, by sources of equal authority."""

    mutates = _actions(pack, MutateAction)
    entity = _pick(
        stream, registry, {action.referent_type for action in mutates}
    )
    if entity is None:
        return None

    relation = stream.choice(
        sorted(
            {
                action.relation
                for action in mutates
                if action.referent_type == entity.type
            }
        )
    )

    # Two different sources of one authority: a source alone in its tier
    # could only be named twice, which a speaker may not be.
    tiers: dict[int, list[str]] = {}
    for source in sorted(pack.sources.values(), key=lambda s: s.id):
        tiers.setdefault(source.authority, []).append(source.id)
    shared = [tier for _, tier in sorted(tiers.items()) if len(tier) > 1]
    first, second = stream.sample(stream.choice(shared), 2)

    return ConflictDraft(
        session=session,
        initiator=stream.choice(sorted(pack.actors)),
        referent=entity.id,
        relation=relation,
        sources=(first, second),
    )


def _actions[A: (InitAction, MutateAction)](
    pack: LoadedPack, kind: type[A]
) -> list[A]:
    """The pack's ActionTypes of the kind, in name order."""

    return sorted(
        (
            action
            for action in pack.action_types.values()
            if isinstance(action, kind)
        ),
        key=lambda action: action.name,
    )


def _pick(
    stream: random.Random, registry: Registry, types: Collection[str]
) -> Entry | None:
    """Any entity of one of the types, or None if there is none."""

    candidates = _of_types(registry, types)

    return stream.choice(candidates) if candidates else None


def _of_types(registry: Registry, types: Collection[str]) -> list[Entry]:
    """Every entity of one of the types, terminal ones included."""

    # Terminal ones too: a replacement card may replace a closed card.
    return [entry for entry in registry.entries() if entry.type in types]


def _link_types(
    action: InitAction, link: str, pack: LoadedPack
) -> frozenset[str]:
    """The entity types the INIT's link may point at."""

    return pack.entity_types[action.referent_type].links[link]


def _framing(stream: random.Random, action: str, pack: LoadedPack) -> Framing:
    """One of the ways the ActionType occurs."""

    return stream.choice(pack.framings[action])


def _source(stream: random.Random, framing: Framing) -> str | None:
    """The framing's source, or None to leave it to the default."""

    return framing.source if stream.random() < NAMED_SOURCE_CHANCE else None
