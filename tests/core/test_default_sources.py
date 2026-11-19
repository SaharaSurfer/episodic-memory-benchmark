from dataclasses import replace

import pytest

from mbench.core.records.commands import InitCommand
from tests.core.world import WRITES, World, disclosures_in, reprice


def _open(initiator: str, source: str | None) -> InitCommand:
    return InitCommand(
        session=1,
        initiator=initiator,
        action_type="OPEN_DEPOSIT_ACCOUNT",
        writes=WRITES,
        source=source,
    )


def test_a_named_source_wins_over_the_initiators_speaker() -> None:
    disclosures = disclosures_in(World().accept(_open("CLIENT", "statement")))

    assert {d.source for d in disclosures} == {"statement"}


@pytest.mark.parametrize(
    ("initiator", "speaker"), [("CLIENT", "customer"), ("BANK", "operator")]
)
def test_with_no_source_named_the_initiators_speaker_is_the_source(
    initiator: str, speaker: str
) -> None:
    disclosures = disclosures_in(World().accept(_open(initiator, None)))

    assert {d.source for d in disclosures} == {speaker}


def test_a_mutate_with_no_source_named_takes_the_initiators_speaker() -> None:
    world = World()
    account = world.open()
    command = replace(reprice(account, 2, "3.90"), source=None)

    disclosures = disclosures_in(world.accept(command))

    assert [d.source for d in disclosures] == ["operator"]
