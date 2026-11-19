from collections.abc import Iterable, Mapping

from mbench.core.folds.registry import Entry, Stamped, is_contested
from mbench.core.legality._refusal import Reason, Refusal
from mbench.core.legality.role_filters import Verdict, judge_gate
from mbench.core.values.contested import Contested, WorldValue
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import Gate, LoadedPack


def passes(entry: Entry, gate: Gate) -> bool:
    """Whether the entity holds every relation gated, admitted or contested."""

    # A new kind of read here must be added to `_legality_reads` in
    # `mbench/packs/spec.py`.
    # A gate cannot judge a conflict. The pack lists what gates read, so
    # sealing refuses the command instead.
    return judge_gate(entry, gate) is not Verdict.FAIL


def refuse_second_write(
    session: int, current: Mapping[str, Stamped]
) -> Refusal | None:
    """Refuse a write to a pair already written in the command's session."""

    for stamped in current.values():
        if stamped.session == session:
            return Refusal(Reason.PAIR_ALREADY_WRITTEN)

    return None


def refuse_invalid_values(
    relations: Mapping[str, type[ValueClass]],
    stated: Iterable[tuple[str, ValueClass]],
) -> Refusal | None:
    """Refuse a value its relation's class does not hold, or holds invalid."""

    for relation, value in stated:
        if not fits(relations, relation, value):
            return Refusal(Reason.INVALID_VALUE)

    return None


def fits(
    relations: Mapping[str, type[ValueClass]], relation: str, value: ValueClass
) -> bool:
    """Whether the relation is declared and its class holds the value."""

    cls = relations.get(relation)

    return cls is not None and isinstance(value, cls) and value.is_valid()


def refuse_sealed(values: Iterable[Stamped]) -> Refusal | None:
    """Refuse a command touching these values if any is contested."""

    if any(isinstance(current.value, Contested) for current in values):
        return Refusal(Reason.PAIR_SEALED)

    return None


def refuse_sealed_entity(entry: Entry, pack: LoadedPack) -> Refusal | None:
    """Refuse a write to an entity with no truth to read in its gates."""

    return (
        Refusal(Reason.ENTITY_SEALED) if entity_is_sealed(entry, pack) else None
    )


def entity_is_sealed(entry: Entry, pack: LoadedPack) -> bool:
    """Whether a relation legality reads holds a contested value."""

    contested = {r for r in entry.values if is_contested(entry, r)}
    if not contested:
        return False

    return not contested.isdisjoint(pack.relations_legality_reads[entry.type])


def refuse_unchanged_value(
    writes: Mapping[str, WorldValue], current: Mapping[str, Stamped]
) -> Refusal | None:
    """Refuse a write of the value its pair already holds."""

    for relation, stamped in current.items():
        if writes[relation] == stamped.value:
            return Refusal(Reason.UNCHANGED_VALUE)

    return None


def current_values(
    entry: Entry, writes: Mapping[str, WorldValue]
) -> Mapping[str, Stamped]:
    """The current stamped value of each pair the writes touch, if any."""

    return {
        relation: entry.values[relation]
        for relation in writes
        if relation in entry.values
    }
