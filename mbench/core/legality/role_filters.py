from collections.abc import Iterable, Iterator, Mapping
from enum import Enum
from types import MappingProxyType

from mbench.core.folds.registry import Entry, Registry, is_contested, is_live
from mbench.core.records.ids import NodeId
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import Gate, Linker, LoadedPack, RoleFilter


class Verdict(Enum):
    """A filter's or gate's answer on one entity."""

    PASS = "pass"
    FAIL = "fail"
    # The answer would rest on a contested value, which has no truth to read.
    UNDECIDED = "undecided"


_NO_BINDINGS: Mapping[str, NodeId] = MappingProxyType({})


def judge(
    role_filter: RoleFilter,
    entry: Entry,
    registry: Registry,
    pack: LoadedPack,
    bindings: Mapping[str, NodeId] = _NO_BINDINGS,
) -> Verdict:
    """Whether the role filter lets a role bind the entity, given bindings."""

    # Checked first, so a caller's bug never hides behind a failed type.
    if role_filter.of is not None and role_filter.of not in bindings:
        raise ValueError(
            f"{role_filter.name} needs the binding of role {role_filter.of},"
            f" not among {sorted(bindings)}"
        )

    if role_filter.entity_type not in (None, entry.type):
        return Verdict.FAIL

    return _all(
        (
            judge_gate(entry, role_filter.values),
            _judge_live(entry, pack) if role_filter.live else Verdict.PASS,
            *(
                _judge_no_live_linker(entry, linker, registry, pack)
                for linker in role_filter.no_live_linkers
            ),
            _judge_of(entry, bindings[role_filter.of])
            if role_filter.of is not None
            else Verdict.PASS,
        )
    )


def judge_gate(entry: Entry, gate: Gate) -> Verdict:
    """Whether the entity holds, for every relation gated, a value admitted."""

    return _all(
        _judge_value(entry, relation, admitted)
        for relation, admitted in gate.items()
    )


def _judge_value(
    entry: Entry, relation: str, admitted: frozenset[ValueClass]
) -> Verdict:
    """Whether the entity's value for the relation is one admitted."""

    if relation not in entry.values:
        return Verdict.FAIL
    if is_contested(entry, relation):
        return Verdict.UNDECIDED

    return (
        Verdict.PASS
        if entry.values[relation].value in admitted
        else Verdict.FAIL
    )


def _judge_live(entry: Entry, pack: LoadedPack) -> Verdict:
    """Whether the entity's current status is surely non-terminal."""

    if _status_is_contested(entry, pack):
        return Verdict.UNDECIDED

    return Verdict.PASS if is_live(entry, pack) else Verdict.FAIL


def _judge_no_live_linker(
    entry: Entry, linker: Linker, registry: Registry, pack: LoadedPack
) -> Verdict:
    """Whether no entity surely live links to the entry the linker's way."""

    # A linker surely live fails the condition whatever a contested one holds.
    return _all(
        _not(_judge_live(other, pack))
        for other in _linkers(entry, linker, registry)
    )


def _judge_of(entry: Entry, binding: NodeId) -> Verdict:
    """Whether one of the entity's links points at the binding."""

    return Verdict.PASS if binding in entry.links.values() else Verdict.FAIL


def _all(verdicts: Iterable[Verdict]) -> Verdict:
    """The verdicts joined by AND: any fail fails, else any undecided."""

    joined = set(verdicts)

    if Verdict.FAIL in joined:
        return Verdict.FAIL
    if Verdict.UNDECIDED in joined:
        return Verdict.UNDECIDED

    return Verdict.PASS


def _not(verdict: Verdict) -> Verdict:
    """The verdict reversed, undecided staying undecided."""

    if verdict is Verdict.UNDECIDED:
        return verdict

    return Verdict.FAIL if verdict is Verdict.PASS else Verdict.PASS


def _status_is_contested(entry: Entry, pack: LoadedPack) -> bool:
    """Whether the entity's status holds a contested value."""

    status = pack.entity_types[entry.type].status

    return status is not None and is_contested(entry, status)


def _linkers(
    entry: Entry, linker: Linker, registry: Registry
) -> Iterator[Entry]:
    """The entities pointing at the entry in the linker's way."""

    return (
        other
        for other in registry.entries()
        if other.type == linker.entity_type
        and other.links.get(linker.link) == entry.id
    )
