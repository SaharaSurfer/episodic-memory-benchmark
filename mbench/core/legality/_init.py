from collections.abc import Mapping
from dataclasses import dataclass

from mbench.core.folds.registry import Entry, Registry, true_value
from mbench.core.legality._caller_bugs import wrong_shape
from mbench.core.legality._clauses import (
    entity_is_sealed,
    fits,
    passes,
    refuse_invalid_values,
)
from mbench.core.legality._disclosures import disclosure_source, disclosures
from mbench.core.legality._refusal import Reason, Refusal
from mbench.core.legality.role_filters import Verdict, judge
from mbench.core.records.commands import InitCommand
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import InitEvent, Link, Record
from mbench.core.values.protocol import ValueClass, Zone, ZonedValueClass
from mbench.packs.spec import ByType, Copy, EntityType, InitAction, LoadedPack


@dataclass(frozen=True)
class Init:
    """An INIT with its endpoints and what derives from them."""

    command: InitCommand
    action: InitAction
    source: str
    endpoints: Mapping[str, Entry]
    # The links whose role filter cannot judge its endpoint for a conflict.
    undecided: frozenset[str]
    derived: Mapping[str, ValueClass]
    copied: Mapping[str, NodeId]
    # The command's values and the derived ones: all the event writes.
    writes: Mapping[str, ValueClass]

    def records(self, allocator: IdAllocator) -> tuple[Record, ...]:
        """The INIT event, then a default disclosure per value and link."""

        event = InitEvent(
            session=self.command.session,
            initiator=self.command.initiator,
            action_type=self.command.action_type,
            new_id=allocator.allocate(),
            writes=self.writes,
            links={**self.command.links, **self.copied},
        )

        links = {link: Link(target) for link, target in event.links.items()}

        return (
            event,
            *disclosures(
                event,
                event.new_id,
                {**event.writes, **links},
                self.source,
                allocator,
            ),
        )


def checked(
    command: InitCommand, registry: Registry, pack: LoadedPack
) -> Refusal | Init:
    """The INIT resolved, or the first clause that refuses it."""

    action = _init_action(command, pack)
    _check_links(command, action, pack)
    _check_fixed_values(command, action)
    _check_no_derived_writes(command, action)
    source = disclosure_source(command, pack)

    init = _resolve_endpoints(command, action, source, registry, pack)
    if isinstance(init, Refusal):
        return init

    entity_type = pack.entity_types[action.referent_type]
    refusal = (
        refuse_invalid_values(entity_type.relations, command.writes.items())
        or _refuse_init_on_conflict(init, registry, pack)
        or _refuse_anchor(entity_type, init.writes, registry)
    )
    if refusal is None:
        _check_derivations(init, pack)

    return refusal or init


def _init_action(command: InitCommand, pack: LoadedPack) -> InitAction:
    """The INIT ActionType the command names."""

    action = pack.action_types[command.action_type]
    if not isinstance(action, InitAction):
        raise wrong_shape(command, action.name)

    return action


def _check_links(
    command: InitCommand, action: InitAction, pack: LoadedPack
) -> None:
    """Raise unless an INIT fills its links and names filters it can use."""

    # Like a command of the wrong shape: the caller fills every link the
    # INIT does not copy, and a link it lacks or may not name is its bug.
    if command.links.keys() != action.links.keys():
        raise ValueError(
            f"{action.name} takes links {sorted(action.links)},"
            f" not {sorted(command.links)}"
        )
    if not command.filters.keys() <= action.links.keys():
        raise ValueError(
            f"{action.name} writes no link to filter among"
            f" {sorted(command.filters.keys() - action.links.keys())}"
        )

    unknown = set(command.filters.values()) - pack.role_filters.keys()
    if unknown:
        raise ValueError(
            f"{action.name} names role filters the pack lacks:"
            f" {sorted(unknown)}"
        )

    # A command stores no bindings, so replay could not judge one of these.
    relating = sorted(
        name
        for name in set(command.filters.values())
        if pack.role_filters[name].of is not None
    )
    if relating:
        raise ValueError(
            f"{action.name} names role filters relating two roles: {relating}"
        )


def _check_fixed_values(command: InitCommand, action: InitAction) -> None:
    """Raise unless an INIT writes exactly the values its ActionType fixes."""

    # The pack fixes these, so a command that gets one wrong is its caller's
    # bug. Left unwritten, a status would break every later read of it.
    wrong = [
        relation
        for relation, value in action.fixes.items()
        if command.writes.get(relation) != value
    ]
    if wrong:
        raise ValueError(
            f"{action.name} fixes {sorted(wrong)}, the command differs"
        )


def _check_no_derived_writes(command: InitCommand, action: InitAction) -> None:
    """Raise if an INIT names a value its ActionType derives."""

    named = command.writes.keys() & action.derives.keys()
    if named:
        raise ValueError(
            f"{action.name} derives {sorted(named)}, not the command"
        )


def _resolve_endpoints(
    command: InitCommand,
    action: InitAction,
    source: str,
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | Init:
    """Refuse an INIT whose endpoint is missing, mistyped, gated or filtered."""

    targets = pack.entity_types[action.referent_type].links
    endpoints = {}
    undecided = set()

    # An endpoint need not be live: a replacement points at the closed card
    # it replaces. A gate or filter that wants a live one says so.
    for link, endpoint in command.links.items():
        entry = registry.entry(endpoint)

        if entry is None:
            return Refusal(Reason.ENDPOINT_MISSING)
        if entry.type not in targets[link]:
            return Refusal(Reason.ENDPOINT_WRONG_TYPE)
        if not passes(entry, action.links[link]):
            return Refusal(Reason.ENDPOINT_GATE_FAILED)

        verdict = _filter_verdict(command, link, entry, registry, pack)
        if verdict is Verdict.FAIL:
            return Refusal(Reason.ENDPOINT_FILTER_FAILED)
        if verdict is Verdict.UNDECIDED:
            undecided.add(link)

        endpoints[link] = entry

    derived = _derived_values(action, endpoints)

    return Init(
        command=command,
        action=action,
        source=source,
        endpoints=endpoints,
        undecided=frozenset(undecided),
        derived=derived,
        copied=_copied_links(action, endpoints),
        writes={**command.writes, **derived},
    )


def _filter_verdict(
    command: InitCommand,
    link: str,
    entry: Entry,
    registry: Registry,
    pack: LoadedPack,
) -> Verdict:
    """The verdict of the filter named for the link on its endpoint, if any."""

    name = command.filters.get(link)
    if name is None:
        return Verdict.PASS

    return judge(pack.role_filters[name], entry, registry, pack)


def _refuse_init_on_conflict(
    init: Init, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Refuse an INIT whose link's target is sealed, or its filter undecided."""

    # An undecided filter reads a conflict such as a linking entity's
    # contested status, which no relation of the endpoint holds, so sealing
    # it would not catch.
    sealed = any(
        entity_is_sealed(entry, pack) or link in init.undecided
        for link, entry in init.endpoints.items()
    ) or any(
        entity_is_sealed(_linked_entry(target, registry), pack)
        for target in init.copied.values()
    )

    return Refusal(Reason.ENTITY_SEALED) if sealed else None


def _linked_entry(target: NodeId, registry: Registry) -> Entry:
    """The entity a stored link points at."""

    entry = registry.entry(target)
    # A link is stored only to an entity the registry holds, and the registry
    # drops none.
    assert entry is not None

    return entry


def _refuse_anchor(
    entity_type: EntityType,
    writes: Mapping[str, ValueClass],
    registry: Registry,
) -> Refusal | None:
    """Refuse values whose anchor is in the same zone as one of the type's."""

    if not entity_type.anchor:
        return None

    # Closed entities count too: a question may name one, so its anchor
    # must still pick it out alone.
    for entry in registry.entries():
        if entry.type == entity_type.name and all(
            _same_part(writes, entry, part) for part in entity_type.anchor
        ):
            return Refusal(Reason.ANCHOR_SAME_ZONE)

    return None


def _same_part(
    writes: Mapping[str, ValueClass], entry: Entry, part: str
) -> bool:
    """Whether the INIT's anchor part is in the same zone as the entry's."""

    # Nothing yet makes an INIT write every relation, and a part one side
    # lacks cannot make the two anchors alike.
    if part not in writes or part not in entry.values:
        return False

    new, existing = writes[part], entry.values[part].value

    # The loaded type has refused a nameable anchor without zones, so a part
    # without them belongs to a type never named, compared by equality.
    if isinstance(new, ZonedValueClass) and isinstance(existing, type(new)):
        return new.zone(existing) is Zone.SAME

    return new == existing


def _derived_values(
    action: InitAction, endpoints: Mapping[str, Entry]
) -> dict[str, ValueClass]:
    """The values the INIT's derivations give, skipping any with no answer."""

    # A clause may yet refuse the INIT, and a refused INIT needs no derived
    # values, so one with nothing to read is skipped here rather than raised.
    # `_check_derivations` has the final say on an INIT the clauses pass.
    derived = {}

    for relation, derivation in action.derives.items():
        source = endpoints.get(derivation.via)
        value = None if source is None else _derive(derivation, source)
        if value is not None:
            derived[relation] = value

    return derived


def _derive(derivation: Copy | ByType, source: Entry) -> ValueClass | None:
    """The value the derivation reads off its source entity, if any."""

    if isinstance(derivation, ByType):
        return derivation.values.get(source.type)

    return true_value(source, derivation.relation)


def _copied_links(
    action: InitAction, endpoints: Mapping[str, Entry]
) -> dict[str, NodeId]:
    """The links the INIT copies, skipping any with nothing to copy."""

    copied = {}

    for link, derivation in action.copied_links.items():
        source = endpoints.get(derivation.via)
        target = None if source is None else source.links.get(derivation.link)
        if target is not None:
            copied[link] = target

    return copied


def _check_derivations(init: Init, pack: LoadedPack) -> None:
    """Raise if a legal INIT has a derivation with no fitting answer."""

    action = init.action

    # The clauses have passed, so every endpoint exists and none is sealed. A
    # derivation still unanswered has a `via` naming no link or a recipe that
    # cannot work: the pack's bug, and an entity missing the value would break
    # later reads.
    unanswered = (action.derives.keys() | action.copied_links.keys()) - (
        init.derived.keys() | init.copied.keys()
    )
    if unanswered:
        raise LookupError(f"{action.name} cannot derive {sorted(unanswered)}")

    # The pack chose these values, so no command is to blame for a bad one.
    relations = pack.entity_types[action.referent_type].relations
    unfit = [
        relation
        for relation, value in init.derived.items()
        if not fits(relations, relation, value)
    ]
    if unfit:
        raise ValueError(f"{action.name} derives unfit {sorted(unfit)}")
