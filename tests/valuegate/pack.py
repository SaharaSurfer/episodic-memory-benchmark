from dataclasses import dataclass
from typing import ClassVar

from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import (
    Actor,
    EntityType,
    InitAction,
    LoadedPack,
    MutateAction,
    Source,
    SourceKind,
)


@dataclass(frozen=True)
class WickLength(ValueClass):
    """How far a wick stands out of its lantern."""

    tag: ClassVar[str] = "wick_length"
    MEMBERS: ClassVar[frozenset[str]] = frozenset({"long", "medium", "short"})
    payload: str

    def is_valid(self) -> bool:
        """One of the listed lengths."""

        return self.payload in self.MEMBERS

    def render(self) -> str:
        """The length as a word."""

        return self.payload


LONG = WickLength("long")
MEDIUM = WickLength("medium")
SHORT = WickLength("short")

WICK_LENGTH = "wickLength"
LIGHT_LANTERN = "LIGHT_LANTERN"
TRIM_WICK = "TRIM_WICK"

# No status, so nothing but the wick's length can decide the gate.
LANTERN = EntityType("LANTERN", relations={WICK_LENGTH: WickLength})

KEEPER = Actor("KEEPER")

LOADED_PACK = LoadedPack(
    entity_types={LANTERN.name: LANTERN},
    action_types={
        LIGHT_LANTERN: InitAction(LIGHT_LANTERN, referent_type=LANTERN.name),
        # The relation's only MUTATE, as a pack may have no more. Its gate
        # admits one length, so trimming the wick closes the gate behind it.
        TRIM_WICK: MutateAction(
            TRIM_WICK,
            referent_type=LANTERN.name,
            relation=WICK_LENGTH,
            gate={WICK_LENGTH: frozenset({LONG})},
        ),
    },
    actors={KEEPER.name: KEEPER},
    speakers={},
    # With no speaker to state the keeper's acts, a document has to.
    sources={"lamp_log": Source("lamp_log", SourceKind.DOCUMENT, authority=1)},
    owner=KEEPER.name,
)
