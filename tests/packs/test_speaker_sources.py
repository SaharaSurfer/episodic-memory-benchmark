from dataclasses import replace

import pytest

from mbench.packs.spec import Source, SourceKind, Speaker
from tests.testpack.pack import LOADED_PACK


def test_a_speaker_source_with_no_declared_speaker_is_refused() -> None:
    speakers = dict(LOADED_PACK.speakers)
    del speakers["operator"]

    with pytest.raises(ValueError, match="operator"):
        replace(LOADED_PACK, speakers=speakers)


def test_a_speaker_with_no_speaker_source_is_refused() -> None:
    speakers = {**LOADED_PACK.speakers, "teller": Speaker("teller", "BANK")}

    with pytest.raises(ValueError, match="teller"):
        replace(LOADED_PACK, speakers=speakers)


def test_a_speakers_id_declared_as_a_document_is_refused() -> None:
    sources = {
        **LOADED_PACK.sources,
        "operator": Source("operator", SourceKind.DOCUMENT, authority=3),
    }

    with pytest.raises(ValueError, match="operator"):
        replace(LOADED_PACK, sources=sources)
