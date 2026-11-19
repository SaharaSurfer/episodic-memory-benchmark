import pytest

from mbench.packs.spec import Source, SourceKind, Speaker, default_source

SPEAKERS = (Speaker("customer", "CLIENT"), Speaker("operator", "BANK"))
LETTER = Source("letter", SourceKind.DOCUMENT, authority=2)
EMAIL = Source("email", SourceKind.DOCUMENT, authority=2)
SOURCES = (
    Source("customer", SourceKind.SPEAKER, authority=1),
    LETTER,
    EMAIL,
    Source("operator", SourceKind.SPEAKER, authority=3),
)


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
