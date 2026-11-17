from dataclasses import replace

import pytest

from mbench.core.records.commands import InitCommand, MutateCommand
from mbench.core.records.log import READ, Disclosure, Event, Record
from mbench.packs.spec import LoadedPack, SourceKind
from tests.core.world import (
    WRITES,
    World,
    change_fee,
    move,
    read,
    reprice,
)
from tests.testpack.pack import LOADED_PACK


def _disclosures(records: tuple[Record, ...]) -> list[Disclosure]:
    return [r for r in records if isinstance(r, Disclosure)]


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
    disclosures = _disclosures(World().accept(_open("CLIENT", "statement")))

    assert {d.source for d in disclosures} == {"statement"}


@pytest.mark.parametrize(
    ("initiator", "speaker"), [("CLIENT", "customer"), ("BANK", "operator")]
)
def test_with_no_source_named_the_initiators_speaker_is_the_source(
    initiator: str, speaker: str
) -> None:
    disclosures = _disclosures(World().accept(_open(initiator, None)))

    assert {d.source for d in disclosures} == {speaker}


def test_a_mutate_with_no_source_named_takes_the_initiators_speaker() -> None:
    world = World()
    account = world.open()
    command = replace(reprice(account, 2, "3.90"), source=None)

    disclosures = _disclosures(world.accept(command))

    assert [d.source for d in disclosures] == ["operator"]


def test_an_initiator_with_no_speaker_takes_the_first_document() -> None:
    world = World(_bank_off_stage())
    account = world.open()
    command = replace(reprice(account, 2, "3.90"), source=None)

    disclosures = _disclosures(world.accept(command))

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

    with pytest.raises(LookupError):
        world.decide(command)


def test_every_default_disclosure_is_framed_by_its_event() -> None:
    world = World()
    account = world.open()
    commands = (
        reprice(account, 2, "3.90"),
        read(account, 3),
        change_fee(account, 3, "0"),
        move(account, 4, "FREEZE_DEPOSIT_ACCOUNT"),
        read(account, 5),
        move(account, 6, "CLOSE_DEPOSIT_ACCOUNT"),
    )
    for command in commands:
        world.accept(command)

    # A default disclosure follows its event, a READ's follows none.
    framed: list[tuple[Event, Disclosure]] = []
    event: Event | None = None
    for record in world.records:
        if not isinstance(record, Disclosure):
            event = record
        elif record.action_type != READ:
            assert event is not None
            framed.append((event, record))

    # The opening discloses each value it writes, a MUTATE its one value.
    mutates = [c for c in commands if isinstance(c, MutateCommand)]
    assert len(framed) == len(WRITES) + len(mutates)
    for event, disclosure in framed:
        assert (disclosure.action_type, disclosure.initiator) == (
            event.action_type,
            event.initiator,
        )


def test_the_test_pack_declares_the_finance_sources_and_authorities() -> None:
    authorities = {
        id: source.authority for id, source in LOADED_PACK.sources.items()
    }

    assert authorities == {
        "customer": 1,
        "app_notification": 2,
        "email": 2,
        "letter": 2,
        "statement": 2,
        "operator": 3,
    }
