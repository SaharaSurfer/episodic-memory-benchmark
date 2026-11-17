from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from mbench.core.values.protocol import ValueClass

type Gate = Mapping[str, frozenset[ValueClass]]
type Transition = tuple[ValueClass, ValueClass]


@dataclass(frozen=True)
class Pool[V: ValueClass]:
    """A list of values of one class, samplers name it by its key."""

    cls: type[V]
    members: tuple[V, ...]


@dataclass(frozen=True)
class EntityType:
    """A type of entity, its relations' classes and its terminal statuses."""

    name: str
    relations: Mapping[str, type[ValueClass]]
    # The relation holding the status, a type without one is
    # live once it exists.
    status: str | None = None
    terminal: frozenset[ValueClass] = frozenset()

    def __post_init__(self) -> None:
        """Hold the relations read-only, and the terminal statuses as a set."""

        object.__setattr__(
            self, "relations", MappingProxyType(dict(self.relations))
        )
        object.__setattr__(self, "terminal", frozenset(self.terminal))


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
    # The values the referent must hold, per relation, to take the action.
    gate: Gate = field(default_factory=lambda: MappingProxyType({}))
    # A status action writes the status it fixes, so its command names none,
    # and its gate is its source statuses.
    fixes: ValueClass | None = None

    def __post_init__(self) -> None:
        """Hold the gate read-only."""

        object.__setattr__(
            self,
            "gate",
            MappingProxyType(
                {
                    relation: frozenset(admitted)
                    for relation, admitted in self.gate.items()
                }
            ),
        )

    def takes(self, transition: Transition) -> bool:
        """Whether the action can make this change to the relation it writes."""

        before, after = transition
        admitted = self.gate.get(self.relation)

        return (admitted is None or before in admitted) and (
            self.fixes is None or self.fixes == after
        )


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

    def action_for(
        self, entity_type: str, relation: str, transition: Transition
    ) -> MutateAction | None:
        """The ActionType that makes this write on this type, if one does."""

        for action in self.action_types.values():
            if (
                isinstance(action, MutateAction)
                and action.referent_type == entity_type
                and action.relation == relation
                and action.takes(transition)
            ):
                return action

        return None
