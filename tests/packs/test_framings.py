from dataclasses import replace

import pytest

from mbench.packs.spec import Framing, LoadedPack
from tests.testpack.pack import LOADED_PACK


def _framed(**framings: tuple[Framing, ...]) -> LoadedPack:
    """The test pack with exactly these framings."""

    return replace(LOADED_PACK, framings=framings)


@pytest.mark.parametrize(
    ("framings", "expected"),
    [
        ((), False),
        ((Framing("CLIENT", "customer"),), False),
        ((Framing("BANK", "customer"),), False),
        ((Framing("BANK", "letter"),), True),
        ((Framing("CLIENT", "operator"),), True),
        ((Framing("CLIENT", "customer"), Framing("BANK", "operator")), True),
    ],
    ids=[
        "no framing",
        "owner starts, owner's speaker states",
        "bank starts, owner's speaker states",
        "a document states",
        "owner starts, another speaker states",
        "one framing of two qualifies",
    ],
)
def test_the_owner_rule_needs_a_source_other_than_the_owners_speaker(
    framings: tuple[Framing, ...], expected: bool
) -> None:
    pack = _framed(LOCK_CARD=framings)

    assert pack.passes_owner_rule("LOCK_CARD") is expected


@pytest.mark.parametrize(
    ("action", "framing", "named"),
    [
        ("LOCK_CARDS", Framing("BANK", "letter"), "LOCK_CARDS"),
        ("LOCK_CARD", Framing("BANKER", "letter"), "BANKER"),
        ("LOCK_CARD", Framing("BANK", "lettre"), "lettre"),
    ],
    ids=["action", "initiator", "source"],
)
def test_a_framing_naming_something_the_pack_lacks_is_refused(
    action: str, framing: Framing, named: str
) -> None:
    with pytest.raises(ValueError, match=named):
        _framed(**{action: (framing,)})


def test_the_framings_are_read_only() -> None:
    framings = LOADED_PACK.framings

    with pytest.raises(TypeError, match="item assignment"):
        framings["LOCK_CARD"] = ()  # type: ignore[index]


def test_shared_initiators_are_those_both_actions_offer() -> None:
    pack = _framed(
        LOCK_CARD=(Framing("BANK", "letter"), Framing("CLIENT", "email")),
        CLOSE_CARD=(Framing("BANK", "email"),),
    )

    assert pack.shared_initiators("LOCK_CARD", "CLOSE_CARD") == {"BANK"}


def test_a_framing_the_owners_speaker_states_offers_no_initiator() -> None:
    pack = _framed(
        LOCK_CARD=(Framing("BANK", "customer"), Framing("CLIENT", "email")),
        CLOSE_CARD=(Framing("BANK", "email"),),
    )

    assert pack.shared_initiators("LOCK_CARD", "CLOSE_CARD") == frozenset()
