import copy
from dataclasses import replace

import pytest

from mbench.core.folds.registry import Registry, fold_world
from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.log_builder import DryRun, LogBuilder
from mbench.core.records.commands import Command, EventCommand, MutateCommand
from mbench.core.records.log import AcceptedCommand, Log
from mbench.core.values.factory import (
    AgreeingDraft,
    AvoidList,
    ConflictDraft,
    Factory,
    Fillable,
    FillReason,
    FillRefusal,
)
from tests.core.world import (
    ISSUED_IN,
    MISSING,
    OPENED_IN,
    created_id,
    issue,
    open_account,
    read,
    reprice,
    unfilled_fee_change,
    unfilled_opening,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import LastFour


def _builder() -> LogBuilder:
    return LogBuilder(LOADED_PACK, id_seed=0)


def _accepted(run: DryRun, command: Command) -> AcceptedCommand:
    """The run's acceptance of a command expected to pass."""

    outcome = run.decide(command)
    assert isinstance(outcome, AcceptedCommand)

    return outcome


def _committed(builder: LogBuilder, command: Command) -> AcceptedCommand:
    """The command's acceptance, committed as a one-step run."""

    run = builder.dry_run()
    outcome = _accepted(run, command)
    builder.commit(run)

    return outcome


def _step_on_missing_account() -> MutateCommand:
    """A step the predicate refuses, as no entity holds its referent's id."""

    return reprice(MISSING, OPENED_IN, "3.90")


def test_a_later_step_can_link_to_an_entity_an_earlier_step_created() -> None:
    run = _builder().dry_run()

    opened = _accepted(run, open_account(OPENED_IN))
    account = created_id(opened.records)
    issued = _accepted(run, issue(account, ISSUED_IN))

    assert run.accepted == (opened, issued)
    assert run.registry.ids() == {account, created_id(issued.records)}


def test_a_dropped_run_leaves_the_log_and_registry_as_they_were() -> None:
    builder = _builder()
    _committed(builder, open_account(OPENED_IN))
    log, registry = builder.log, builder.registry

    _accepted(builder.dry_run(), open_account(2, lastFour=LastFour("8203")))

    assert builder.log is log
    assert builder.registry is registry


def test_commit_appends_the_accepted_commands_unchanged() -> None:
    builder = _builder()
    run = builder.dry_run()
    opened = _accepted(run, open_account(OPENED_IN))
    issued = _accepted(run, issue(created_id(opened.records), ISSUED_IN))

    builder.commit(run)

    assert builder.log.accepted == (opened, issued)
    assert builder.log.accepted[0] is opened
    assert builder.log.sessions.keys() == {OPENED_IN, ISSUED_IN}


def test_commit_advances_the_registry_to_the_fold_of_the_log() -> None:
    builder = _builder()
    run = builder.dry_run()
    opened = _accepted(run, open_account(OPENED_IN))
    _accepted(run, reprice(created_id(opened.records), ISSUED_IN, "3.90"))

    builder.commit(run)

    assert builder.registry == fold_world(builder.log.records, LOADED_PACK)


def test_ids_after_a_commit_are_those_of_the_candidate_run_alone() -> None:
    alone = _builder()
    among_others = _builder()
    other = open_account(OPENED_IN, lastFour=LastFour("8203"))

    _accepted(among_others.dry_run(), other)
    picked = among_others.dry_run()
    _accepted(among_others.dry_run(), other)
    _accepted(picked, open_account(OPENED_IN))
    among_others.commit(picked)
    _committed(alone, open_account(OPENED_IN))

    assert _committed(among_others, other) == _committed(alone, other)
    assert among_others.log == alone.log


def test_ids_run_on_across_commits_as_within_one_run() -> None:
    other = open_account(ISSUED_IN, lastFour=LastFour("8203"))
    builder = _builder()
    first = _committed(builder, open_account(OPENED_IN))
    second = _committed(builder, other)

    run = _builder().dry_run()

    assert _accepted(run, open_account(OPENED_IN)) == first
    assert _accepted(run, other) == second


def test_stepping_a_committed_run_shifts_no_id_of_the_builder() -> None:
    undisturbed = _builder()
    _committed(undisturbed, open_account(OPENED_IN))
    builder = _builder()
    run = builder.dry_run()
    _accepted(run, open_account(OPENED_IN))
    builder.commit(run)
    other = open_account(ISSUED_IN, lastFour=LastFour("8203"))

    _accepted(run, other)

    assert _committed(builder, other) == _committed(undisturbed, other)


def _refused_run(builder: LogBuilder) -> DryRun:
    """A run whose one step the predicate refused."""

    run = builder.dry_run()
    assert isinstance(run.decide(_step_on_missing_account()), Refusal)

    return run


def test_a_refusal_is_returned_and_adds_nothing_to_the_run() -> None:
    run = _builder().dry_run()

    outcome = run.decide(_step_on_missing_account())

    assert outcome == Refusal(Reason.REFERENT_MISSING)
    assert run.accepted == ()


def test_a_step_after_a_refusal_raises() -> None:
    run = _refused_run(_builder())

    with pytest.raises(ValueError, match="refused"):
        run.decide(open_account(OPENED_IN))


def test_committing_a_refused_run_raises_and_changes_nothing() -> None:
    builder = _builder()
    run = builder.dry_run()
    _accepted(run, open_account(OPENED_IN))
    assert isinstance(run.decide(_step_on_missing_account()), Refusal)

    with pytest.raises(ValueError, match="refused"):
        builder.commit(run)

    assert builder.log == Log()


def test_committing_a_run_after_the_log_moved_on_raises() -> None:
    builder = _builder()
    stale = builder.dry_run()
    _accepted(stale, open_account(OPENED_IN))
    _committed(builder, open_account(OPENED_IN))
    log = builder.log

    with pytest.raises(ValueError, match="moved on"):
        builder.commit(stale)

    assert builder.log is log


def test_committing_a_run_twice_raises() -> None:
    builder = _builder()
    run = builder.dry_run()
    _accepted(run, open_account(OPENED_IN))
    builder.commit(run)

    with pytest.raises(ValueError, match="moved on"):
        builder.commit(run)


def test_committing_an_empty_run_leaves_other_runs_committable() -> None:
    builder = _builder()
    sibling = builder.dry_run()
    opened = _accepted(sibling, open_account(OPENED_IN))

    builder.commit(builder.dry_run())
    builder.commit(sibling)

    assert builder.log.accepted == (opened,)


def test_committing_a_run_of_another_builder_raises() -> None:
    foreign = _builder().dry_run()
    _accepted(foreign, open_account(OPENED_IN))

    # Both logs are empty and so equal: only their identity tells them apart.
    with pytest.raises(ValueError, match="moved on"):
        _builder().commit(foreign)


def test_the_result_of_a_refused_run_raises() -> None:
    run = _refused_run(_builder())

    with pytest.raises(ValueError, match="refused"):
        run.result()


def test_the_result_of_a_run_refused_a_fill_raises() -> None:
    run = _builder().dry_run()
    unfillable = unfilled_fee_change(MISSING, OPENED_IN)
    assert isinstance(
        run.fill_and_decide(unfillable, Factory(0, LOADED_PACK)), FillRefusal
    )

    with pytest.raises(ValueError, match="refused"):
        run.result()


def test_a_result_carries_the_runs_start_steps_and_registry() -> None:
    builder = _builder()
    _committed(builder, open_account(OPENED_IN))
    run = builder.dry_run()
    opened = _accepted(run, open_account(ISSUED_IN, lastFour=LastFour("8203")))

    result = run.result()

    assert result.start is builder.log
    assert result.accepted == (opened,)
    assert result.registry == fold_world(
        builder.log.append(result.accepted).records, LOADED_PACK
    )


def test_stepping_a_run_after_its_result_draws_nothing_from_it() -> None:
    run = _builder().dry_run()
    _accepted(run, open_account(OPENED_IN))
    result = run.result()
    expected = copy.copy(result.allocator).allocate()

    _accepted(run, open_account(ISSUED_IN, lastFour=LastFour("8203")))

    assert result.allocator.allocate() == expected


class _UnusableFactory(Factory):
    """A factory that fails the test if it is asked to fill anything."""

    def fill(
        self,
        command: Fillable,
        registry: Registry,
        avoid: AvoidList | None = None,
    ) -> EventCommand:
        raise AssertionError("the command should not have been filled")


def test_filling_a_step_reads_the_registry_of_the_run() -> None:
    run = _builder().dry_run()
    factory = Factory(0, LOADED_PACK)
    opened = run.fill_and_decide(unfilled_opening(), factory)
    assert isinstance(opened, AcceptedCommand)
    account = created_id(opened.records)

    fee = run.fill_and_decide(unfilled_fee_change(account, ISSUED_IN), factory)

    assert isinstance(fee, AcceptedCommand)
    assert run.accepted == (opened, fee)


@pytest.mark.parametrize(
    "draft",
    [
        AgreeingDraft(
            session=ISSUED_IN,
            initiator="BANK",
            action_type="CHANGE_ACCOUNT_FEE",
            referent=MISSING,
            sources=("letter", "app_notification"),
        ),
        ConflictDraft(
            session=ISSUED_IN,
            initiator="BANK",
            referent=MISSING,
            relation="hasMonthlyFee",
            sources=("letter", "email"),
        ),
    ],
    ids=["agreeing", "conflicting"],
)
def test_a_draft_is_filled_and_decided_in_the_run(
    draft: AgreeingDraft | ConflictDraft,
) -> None:
    run = _builder().dry_run()
    factory = Factory(0, LOADED_PACK)
    opened = run.fill_and_decide(unfilled_opening(), factory)
    assert isinstance(opened, AcceptedCommand)

    outcome = run.fill_and_decide(
        replace(draft, referent=created_id(opened.records)), factory
    )

    assert isinstance(outcome, AcceptedCommand)
    assert run.accepted == (opened, outcome)


def test_a_fill_refusal_is_returned_and_ends_the_run() -> None:
    builder = _builder()
    run = builder.dry_run()
    unfillable = unfilled_fee_change(MISSING, OPENED_IN)

    outcome = run.fill_and_decide(unfillable, Factory(0, LOADED_PACK))

    assert outcome == FillRefusal(FillReason.NO_CURRENT_VALUE)
    with pytest.raises(ValueError, match="refused"):
        run.decide(open_account(OPENED_IN))
    with pytest.raises(ValueError, match="refused"):
        builder.commit(run)


def test_a_filled_step_the_predicate_refuses_ends_the_run() -> None:
    run = _builder().dry_run()
    unlinked_card = replace(issue(MISSING, OPENED_IN), writes={})

    outcome = run.fill_and_decide(unlinked_card, Factory(0, LOADED_PACK))

    assert isinstance(outcome, Refusal)
    with pytest.raises(ValueError, match="refused"):
        run.decide(open_account(OPENED_IN))


def test_filling_after_a_refusal_raises_before_the_factory_runs() -> None:
    run = _refused_run(_builder())

    with pytest.raises(ValueError, match="refused"):
        run.fill_and_decide(
            unfilled_opening(), _UnusableFactory(0, LOADED_PACK)
        )


def test_a_step_before_the_runs_last_session_raises() -> None:
    run = _builder().dry_run()
    _accepted(run, open_account(ISSUED_IN))

    # Would be refused if it were checked, so raising shows it was not.
    with pytest.raises(ValueError, match="session"):
        run.decide(_step_on_missing_account())


def test_a_step_before_the_logs_last_session_raises() -> None:
    builder = _builder()
    _committed(builder, open_account(ISSUED_IN))

    with pytest.raises(ValueError, match="session"):
        builder.dry_run().decide(_step_on_missing_account())


def test_a_step_to_fill_before_the_last_session_raises_unfilled() -> None:
    builder = _builder()
    _committed(builder, open_account(ISSUED_IN))

    with pytest.raises(ValueError, match="session"):
        builder.dry_run().fill_and_decide(
            unfilled_opening(OPENED_IN), _UnusableFactory(0, LOADED_PACK)
        )


def test_a_step_out_of_order_does_not_end_the_run() -> None:
    run = _builder().dry_run()
    opened = _accepted(run, open_account(ISSUED_IN))

    with pytest.raises(ValueError, match="session"):
        run.decide(open_account(OPENED_IN))

    assert run.accepted == (opened,)
    _accepted(run, read(created_id(opened.records), ISSUED_IN))


def test_the_same_session_and_skipped_sessions_are_allowed() -> None:
    run = _builder().dry_run()
    opened = _accepted(run, open_account(OPENED_IN))
    account = created_id(opened.records)

    _accepted(run, read(account, OPENED_IN))
    _accepted(run, read(account, OPENED_IN + 5))

    assert len(run.accepted) == 3
