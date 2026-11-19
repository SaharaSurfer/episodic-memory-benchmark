from dataclasses import replace

import pytest

from mbench.packs.spec import Actor, Source, SourceKind, Speaker, default_source
from tests.testpack.pack import LOADED_PACK

SPEAKERS = (Speaker("customer", "CLIENT"), Speaker("operator", "BANK"))
LETTER = Source("letter", SourceKind.DOCUMENT, authority=2)
EMAIL = Source("email", SourceKind.DOCUMENT, authority=2)
SOURCES = (
    Source("customer", SourceKind.SPEAKER, authority=1),
    LETTER,
    EMAIL,
    Source("operator", SourceKind.SPEAKER, authority=3),
)
REGULATOR = Actor("REGULATOR")


def test_a_named_source_wins_over_the_initiators_speaker() -> None:
    assert default_source("CLIENT", "email", SPEAKERS, SOURCES) == "email"


@pytest.mark.parametrize(
    ("initiator", "speaker"), [("CLIENT", "customer"), ("BANK", "operator")]
)
def test_with_no_source_named_the_initiators_speaker_states_it(
    initiator: str, speaker: str
) -> None:
    assert default_source(initiator, None, SPEAKERS, SOURCES) == speaker


def test_an_initiator_with_no_speaker_takes_the_first_document() -> None:
    assert default_source("REGULATOR", None, SPEAKERS, SOURCES) == "letter"


def test_with_no_speaker_for_the_initiator_and_no_document_it_raises() -> None:
    speaking = [
        source for source in SOURCES if source.kind is SourceKind.SPEAKER
    ]

    with pytest.raises(LookupError, match="REGULATOR"):
        default_source("REGULATOR", None, SPEAKERS, speaking)


def test_the_pack_holds_each_actors_default_source() -> None:
    assert LOADED_PACK.default_sources == {
        "CLIENT": "customer",
        "BANK": "operator",
    }


def test_an_actor_with_no_speaker_in_a_pack_with_no_document_is_refused() -> (
    None
):
    speaking = {
        id: source
        for id, source in LOADED_PACK.sources.items()
        if source.kind is SourceKind.SPEAKER
    }

    with pytest.raises(ValueError, match="REGULATOR"):
        replace(
            LOADED_PACK,
            actors={**LOADED_PACK.actors, "REGULATOR": REGULATOR},
            sources=speaking,
            # The framings name documents, which this pack no longer has.
            framings={},
        )


def test_an_actor_with_no_speaker_follows_the_documents_given() -> None:
    sources = {
        id: source
        for id, source in LOADED_PACK.sources.items()
        if id != "app_notification"
    }
    pack = replace(
        LOADED_PACK,
        actors={**LOADED_PACK.actors, "REGULATOR": REGULATOR},
        sources=sources,
    )

    assert pack.default_sources["REGULATOR"] == "email"
