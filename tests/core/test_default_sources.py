from dataclasses import replace

import pytest

from mbench.core.records.commands import InitCommand
from mbench.packs.spec import LoadedPack, SourceKind
from tests.core.world import WRITES, World, disclosures_in, reprice
from tests.testpack.pack import LOADED_PACK


def _open(initiator: str, source: str | None) -> InitCommand:
    return InitCommand(
        session=1,
        initiator=initiator,
        action_type="OPEN_DEPOSIT_ACCOUNT",
        writes=WRITES,
        source=source,
    )


def _bank_off_stage() -> LoadedPack:
    # The bank's speaker goes, and its source with it.
    gone = {
        id
        for id, speaker in LOADED_PACK.speakers.items()
        if speaker.represents == "BANK"
    }

    return replace(
        LOADED_PACK,
        speakers={
            id: s for id, s in LOADED_PACK.speakers.items() if id not in gone
        },
        sources={
            id: s for id, s in LOADED_PACK.sources.items() if id not in gone
        },
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


def test_an_initiator_with_no_speaker_takes_the_first_document() -> None:
    world = World(_bank_off_stage())
    account = world.open()
    command = replace(reprice(account, 2, "3.90"), source=None)

    disclosures = disclosures_in(world.accept(command))

    assert [d.source for d in disclosures] == ["app_notification"]


def test_with_no_speaker_for_the_initiator_and_no_document_it_raises() -> None:
    off_stage = _bank_off_stage()
    no_documents = replace(
        off_stage,
        sources={
            id: source
            for id, source in off_stage.sources.items()
            if source.kind is SourceKind.SPEAKER
        },
    )
    world = World(no_documents)
    account = world.open()
    command = replace(reprice(account, 2, "3.90"), source=None)

    with pytest.raises(LookupError, match="no source can state"):
        world.decide(command)
