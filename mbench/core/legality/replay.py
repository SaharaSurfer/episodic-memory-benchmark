from dataclasses import dataclass

from mbench.core.folds.registry import Registry, fold_world
from mbench.core.legality.predicate import (
    Refusal,
    check,
    refuse_untrue_disclosure,
)
from mbench.core.records.log import AcceptedCommand, Disclosure, Log
from mbench.packs.spec import LoadedPack


@dataclass(frozen=True)
class IllegalPosition:
    """The accepted command a replay stopped at, and why it is illegal."""

    position: int
    refusal: Refusal


def replay(log: Log, pack: LoadedPack) -> IllegalPosition | None:
    """The log's first illegal position, walking it from empty, if any."""

    registry = Registry()

    for position, accepted in enumerate(log.accepted):
        refusal = check(accepted.command, registry, pack)
        if refusal is None:
            registry = fold_world(accepted.records, pack, registry)
            refusal = _refuse_stored_disclosures(accepted, registry)

        if refusal is not None:
            return IllegalPosition(position, refusal)

    return None


def _refuse_stored_disclosures(
    accepted: AcceptedCommand, registry: Registry
) -> Refusal | None:
    """The refusal of the command's first untrue disclosure, if any."""

    # Re-running a READ copies the registry and always passes, so only what
    # it stored can show that an earlier command has made it untrue.
    for record in accepted.records:
        if isinstance(record, Disclosure):
            refusal = refuse_untrue_disclosure(record, registry)
            if refusal is not None:
                return refusal

    return None
