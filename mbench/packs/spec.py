from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from mbench.core.values.protocol import ValueClass


@dataclass(frozen=True)
class Pool[V: ValueClass]:
    """A list of values of one class, samplers name it by its key."""

    cls: type[V]
    members: tuple[V, ...]


@dataclass(frozen=True)
class EntityType:
    """A type of entity and the value class each of its relations holds."""

    name: str
    relations: Mapping[str, type[ValueClass]]

    def __post_init__(self) -> None:
        """Hold the relations read-only."""

        object.__setattr__(
            self, "relations", MappingProxyType(dict(self.relations))
        )


@dataclass(frozen=True)
class InitAction:
    """An ActionType that creates an entity of its referent type."""

    name: str
    referent_type: str


@dataclass(frozen=True)
class MutateAction:
    """An ActionType that writes one relation of an entity of its type."""

    name: str
    referent_type: str
    relation: str


type ActionType = InitAction | MutateAction


@dataclass(frozen=True)
class LoadedPack:
    """What the core reads of a pack: its types and ActionTypes by name."""

    entity_types: Mapping[str, EntityType]
    action_types: Mapping[str, ActionType]

    def __post_init__(self) -> None:
        """Hold both tables read-only."""

        object.__setattr__(
            self, "entity_types", MappingProxyType(dict(self.entity_types))
        )
        object.__setattr__(
            self, "action_types", MappingProxyType(dict(self.action_types))
        )
