import copy

from mbench.core.folds.registry import Registry, fold_world
from mbench.core.legality.predicate import Refusal, decide
from mbench.core.records.commands import Command
from mbench.core.records.ids import IdAllocator
from mbench.core.records.log import AcceptedCommand, Log
from mbench.core.values.factory import Factory, Fillable, FillRefusal
from mbench.packs.spec import LoadedPack


class DryRun:
    """One candidate's steps, tried on copies of the builder's state."""

    def __init__(
        self,
        pack: LoadedPack,
        log: Log,
        registry: Registry,
        allocator: IdAllocator,
    ) -> None:
        """Start at the log's end, drawing ids from the allocator given."""

        self._pack = pack
        self._log = log
        self._registry = registry
        self._allocator = allocator
        self._accepted: tuple[AcceptedCommand, ...] = ()
        self._refused = False

    @property
    def accepted(self) -> tuple[AcceptedCommand, ...]:
        """The commands accepted so far, in order."""

        return self._accepted

    @property
    def registry(self) -> Registry:
        """The registry as of the last accepted step."""

        return self._registry

    def decide(self, command: Command) -> AcceptedCommand | Refusal:
        """Decide the command here, folding it in if it is accepted."""

        self._check_step(command)

        return self._decide(command)

    def fill_and_decide(
        self, command: Fillable, factory: Factory
    ) -> AcceptedCommand | Refusal | FillRefusal:
        """Have the factory fill the command here, then decide it."""

        self._check_step(command)

        filled = factory.fill(command, self._registry)
        if isinstance(filled, FillRefusal):
            self._refused = True
            return filled

        return self._decide(filled)

    def _decide(self, command: Command) -> AcceptedCommand | Refusal:
        """The predicate's outcome, kept in the run."""

        outcome = decide(command, self._registry, self._pack, self._allocator)
        if isinstance(outcome, Refusal):
            self._refused = True
            return outcome

        self._registry = fold_world(outcome.records, self._pack, self._registry)
        self._accepted += (outcome,)

        return outcome

    def _check_not_refused(self) -> None:
        """Raise if a step of this run was refused."""

        if self._refused:
            raise ValueError("this dry run was refused")

    def _check_step(self, command: Command) -> None:
        """Raise if the command cannot be this run's next step."""

        self._check_not_refused()

        # Replay cannot catch this: the merged log is sorted by session, which
        # would hide that later commands were chosen against another order.
        earlier = self._accepted or self._log.accepted
        if earlier and command.session < earlier[-1].command.session:
            raise ValueError(
                f"session {command.session} is before the last accepted "
                f"command's, {earlier[-1].command.session}"
            )


class LogBuilder:
    """A log under construction, with its registry and id allocator."""

    def __init__(self, pack: LoadedPack, id_seed: int) -> None:
        """Start an empty log over the pack."""

        self._pack = pack
        self._log = Log()
        self._registry = Registry()
        self._allocator = IdAllocator(id_seed)

    @property
    def log(self) -> Log:
        """The log as committed so far."""

        return self._log

    @property
    def registry(self) -> Registry:
        """The registry at the end of the log."""

        return self._registry

    def dry_run(self) -> DryRun:
        """A run from the end of the log, on its own copy of the allocator."""

        return DryRun(
            self._pack, self._log, self._registry, copy.copy(self._allocator)
        )

    def commit(self, run: DryRun) -> None:
        """Add the run's accepted commands to the log, unchanged."""

        run._check_not_refused()

        # By identity: another builder's empty log equals this one's.
        if run._log is not self._log:
            raise ValueError("the log has moved on from this dry run's start")

        # Nothing to add, and a new log object would make other runs stale.
        if not run.accepted:
            return

        self._log = self._log.append(run.accepted)
        self._registry = run.registry

        # Copied again, so a step on the committed run draws nothing from it.
        self._allocator = copy.copy(run._allocator)
