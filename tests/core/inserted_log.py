import copy
import random
from dataclasses import dataclass

from mbench.core.folds.registry import fold_world
from mbench.core.legality.replay import replay
from mbench.core.log_builder import DryRun
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import (
    AcceptedCommand,
    Disclosure,
    InitEvent,
    Log,
)
from mbench.core.values.factory import Factory
from mbench.packs.spec import LoadedPack
from tests.core.generated_log import draw_and_decide
from tests.testpack.pack import LOADED_PACK


@dataclass(frozen=True)
class ExtendedLog:
    """A base log with commands inserted, and where they went."""

    log: Log
    # The positions in the log of the inserted commands, in order.
    inserted: tuple[int, ...]
    # Commands accepted at their boundary whose log then failed to replay.
    discarded: int


def insert_commands(
    base: Log, seed: int, attempts: int, pack: LoadedPack = LOADED_PACK
) -> ExtendedLog:
    """The base log with commands inserted between its own; it replays clean."""

    stream = random.Random(seed)
    factory = Factory(stream.getrandbits(32), pack)
    # Every base id is used, so no inserted record can take one.
    allocator = IdAllocator(stream.getrandbits(32), used=_node_ids(base))
    accepted = list(base.accepted)
    inserted: list[bool] = [False] * len(accepted)
    discarded = 0

    for _ in range(attempts):
        boundary = stream.randint(0, len(accepted))
        session = _session_between(stream, accepted, boundary)
        before = Log(sessions=base.sessions).append(accepted[:boundary])

        # A copy, so a command dropped below draws no id from the allocator.
        trial = copy.copy(allocator)
        run = DryRun(pack, before, fold_world(before.records, pack), trial)
        outcome = draw_and_decide(run, session, stream, factory, pack)
        if not isinstance(outcome, AcceptedCommand):
            continue

        # Legal where it goes is not enough: every later command must stay
        # legal, and its stored disclosures true, after it.
        candidate = [*accepted[:boundary], outcome, *accepted[boundary:]]
        if replay(_extended(base, candidate), pack) is not None:
            discarded += 1
            continue

        accepted = candidate
        inserted.insert(boundary, True)
        allocator = trial

    return ExtendedLog(
        log=_extended(base, accepted),
        inserted=tuple(
            position for position, flag in enumerate(inserted) if flag
        ),
        discarded=discarded,
    )


def _node_ids(log: Log) -> set[NodeId]:
    """Every id the log's records were allocated."""

    return {
        record.new_id if isinstance(record, InitEvent) else record.node_id
        for record in log.records
        if isinstance(record, InitEvent | Disclosure)
    }


def _extended(base: Log, accepted: list[AcceptedCommand]) -> Log:
    """A log of the commands, keeping the base log's session rows."""

    return Log(sessions=base.sessions).append(accepted)


def _session_between(
    stream: random.Random, accepted: list[AcceptedCommand], boundary: int
) -> int:
    """A session no earlier than the command before, nor later than after."""

    # The log is not checked for session order once built, so the helper
    # must keep it: either neighbour's session is fine, as is any between.
    lowest = accepted[boundary - 1].command.session if boundary > 0 else 1
    if boundary < len(accepted):
        highest = accepted[boundary].command.session
    else:
        highest = lowest + 1

    return stream.randint(lowest, highest)
