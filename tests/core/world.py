from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType

from mbench.core.folds.registry import fold_world
from mbench.core.legality.predicate import Command, Refusal, decide
from mbench.core.records.commands import (
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import InitEvent, Record
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import (
    DepositKind,
    InterestRate,
    LastFour,
    LifecycleStatus,
    MonetaryAmount,
    ProductName,
)

OPENED_IN = 1
OPENING_RATE = "4.25"

# Read-only, since every test shares it as the opening's writes.
WRITES: Mapping[str, ValueClass] = MappingProxyType(
    {
        "kind": DepositKind("savings"),
        "lastFour": LastFour("4471"),
        "productName": ProductName("High Yield Savings"),
        "hasInterestRate": InterestRate(Decimal(OPENING_RATE)),
        "hasMonthlyFee": MonetaryAmount(Decimal("5")),
        "hasStatus": LifecycleStatus("active"),
    }
)


class World:
    """A log built one accepted command at a time."""

    def __init__(self, pack: LoadedPack = LOADED_PACK) -> None:
        """Start an empty log over the pack, with its own allocator."""

        self.pack = pack
        self.records: tuple[Record, ...] = ()
        self.allocator = IdAllocator(seed=0)

    def decide(self, command: Command) -> tuple[Record, ...] | Refusal:
        """Decide the command against the log so far, appending nothing."""

        registry = fold_world(self.records, self.pack)

        return decide(command, registry, self.pack, self.allocator)

    def accept(self, command: Command) -> tuple[Record, ...]:
        """Decide the command against the log so far and append its records."""

        outcome = self.decide(command)
        assert not isinstance(outcome, Refusal)

        self.records += outcome
        return outcome

    def open(self) -> NodeId:
        """Open a deposit account in the first session, and give its id."""

        event, *_ = self.accept(
            InitCommand(
                session=OPENED_IN,
                initiator="client",
                action_type="OPEN_DEPOSIT_ACCOUNT",
                source="customer",
                writes=WRITES,
            )
        )
        assert isinstance(event, InitEvent)
        return event.new_id


def change_fee(referent: NodeId, session: int, amount: str) -> MutateCommand:
    """A command setting the account's monthly fee to the amount."""

    return MutateCommand(
        session=session,
        initiator="bank",
        action_type="CHANGE_ACCOUNT_FEE",
        source="letter",
        referent=referent,
        value=MonetaryAmount(Decimal(amount)),
    )


def reprice(referent: NodeId, session: int, rate: str) -> MutateCommand:
    """A command setting the account's interest rate to the rate."""

    return MutateCommand(
        session=session,
        initiator="bank",
        action_type="REPRICE_DEPOSIT_ACCOUNT",
        source="letter",
        referent=referent,
        value=InterestRate(Decimal(rate)),
    )


def move(referent: NodeId, session: int, action_type: str) -> MutateCommand:
    """A command taking the account through a status move, naming no value."""

    return MutateCommand(
        session=session,
        initiator="bank",
        action_type=action_type,
        source="letter",
        referent=referent,
    )


def read(entity: NodeId, session: int) -> ReadCommand:
    """A command in which the operator states the entity's current values."""

    return ReadCommand(
        session=session,
        initiator="client",
        source="operator",
        entity=entity,
    )
