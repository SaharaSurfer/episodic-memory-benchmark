from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

from mbench.core.folds.graph import Graph, fold_trace
from mbench.core.folds.registry import Registry, fold_world
from mbench.core.legality.predicate import Refusal, decide
from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    Command,
    ConflictingDoubleDisclosureCommand,
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import (
    AcceptedCommand,
    Disclosure,
    InitEvent,
    Log,
    Record,
)
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack
from tests.core.records.handmade import OPEN_ACCOUNT
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import (
    ACTIVE,
    INACTIVE,
    CardType,
    DepositKind,
    InterestRate,
    LastFour,
    MonetaryAmount,
    ProductName,
)

OPENED_IN = 1
OPENING_RATE = "4.25"
ISSUED_IN = 2
CARD_LINK = "hasCorrespondingAccount"

# No entity ever holds this id.
MISSING = NodeId("zzzzz")

# Each account the world opens takes the next, so no two share an anchor. The
# first is the one in WRITES, so an opening with WRITES as they are clashes
# with the world's first account. Every two are far, so none is another's
# lookalike either.
LAST_FOURS = ("4471", "8203", "1658", "3926")

# Read-only, since every test shares it as the opening's writes.
WRITES: Mapping[str, ValueClass] = MappingProxyType(
    {
        "kind": DepositKind("savings"),
        "lastFour": LastFour(LAST_FOURS[0]),
        "productName": ProductName("High Yield Savings"),
        "hasInterestRate": InterestRate(Decimal(OPENING_RATE)),
        "hasMonthlyFee": MonetaryAmount(Decimal("5")),
        "hasStatus": ACTIVE,
    }
)

# Read-only for the same reason. The card type is written by hand here, though
# the pack will derive it from the account.
CARD_WRITES: Mapping[str, ValueClass] = MappingProxyType(
    {
        "cardType": CardType("debit"),
        "lastFour": LastFour("9012"),
        "hasStatus": INACTIVE,
    }
)


class World:
    """A log built one accepted command at a time."""

    def __init__(self, pack: LoadedPack = LOADED_PACK) -> None:
        """Start an empty log over the pack, with its own allocator."""

        self.pack = pack
        self.log = Log()
        self.allocator = IdAllocator(seed=0)
        self.opened_count = 0

    @property
    def records(self) -> tuple[Record, ...]:
        """The log's records so far, in order."""

        return self.log.records

    @property
    def registry(self) -> Registry:
        """The registry folded from the log so far."""

        return fold_world(self.records, self.pack)

    @property
    def graph(self) -> Graph:
        """The graph folded from the log so far."""

        return fold_trace(self.records, self.pack)

    def decide(self, command: Command) -> AcceptedCommand | Refusal:
        """Decide the command against the log so far, appending nothing."""

        return decide(command, self.registry, self.pack, self.allocator)

    def accept(self, command: Command) -> tuple[Record, ...]:
        """Decide the command, append it to the log and give its records."""

        outcome = self.decide(command)
        assert not isinstance(outcome, Refusal)

        self.log = self.log.append([outcome])
        return outcome.records

    def open(self, **changes: ValueClass) -> NodeId:
        """Open an account in the first session, and give its id."""

        changes = {"lastFour": self._next_last_four(), **changes}

        return _created_id(self.accept(open_account(OPENED_IN, **changes)))

    def open_lacking(self, *relations: str) -> NodeId:
        """Open an account without the relations, and give its id."""

        command = opening_lacking(
            OPENED_IN, *relations, lastFour=self._next_last_four()
        )

        return _created_id(self.accept(command))

    def issue_card(self, account: NodeId) -> NodeId:
        """Issue a card on the account in the second session, give its id."""

        return _created_id(self.accept(issue(account, ISSUED_IN)))

    def _next_last_four(self) -> LastFour:
        """The last four no account of this world has taken yet."""

        assert self.opened_count < len(LAST_FOURS), (
            "every last four is taken: add another to LAST_FOURS"
        )
        last_four = LastFour(LAST_FOURS[self.opened_count])

        self.opened_count += 1
        return last_four


def _created_id(records: tuple[Record, ...]) -> NodeId:
    """The id of the entity an INIT's records create."""

    event, *_ = records
    assert isinstance(event, InitEvent)

    return event.new_id


def open_account(session: int, **changes: ValueClass) -> InitCommand:
    """A command opening an account with WRITES, some of them changed."""

    return InitCommand(
        session=session,
        initiator="CLIENT",
        action_type=OPEN_ACCOUNT,
        source="customer",
        writes={**WRITES, **changes},
    )


def opening_lacking(
    session: int, *relations: str, **changes: ValueClass
) -> InitCommand:
    """A command like `open_account`, leaving the relations out."""

    command = open_account(session, **changes)
    writes = {r: v for r, v in command.writes.items() if r not in relations}

    return replace(command, writes=writes)


def issue(account: NodeId, session: int) -> InitCommand:
    """A command issuing a card on the account, filtering no endpoint."""

    return InitCommand(
        session=session,
        initiator="BANK",
        action_type="ISSUE_CARD",
        source="operator",
        writes=CARD_WRITES,
        links={CARD_LINK: account},
    )


def change_fee(referent: NodeId, session: int, amount: str) -> MutateCommand:
    """A command setting the account's monthly fee to the amount."""

    return MutateCommand(
        session=session,
        initiator="BANK",
        action_type="CHANGE_ACCOUNT_FEE",
        source="letter",
        referent=referent,
        value=MonetaryAmount(Decimal(amount)),
    )


def reprice(referent: NodeId, session: int, rate: str) -> MutateCommand:
    """A command setting the account's interest rate to the rate."""

    return MutateCommand(
        session=session,
        initiator="BANK",
        action_type="REPRICE_DEPOSIT_ACCOUNT",
        source="letter",
        referent=referent,
        value=InterestRate(Decimal(rate)),
    )


def agree(
    referent: NodeId,
    session: int,
    rate: str,
    sources: tuple[str, str] = ("letter", "app_notification"),
) -> AgreeingDoubleDisclosureCommand:
    """A command in which two sources both state the account's new rate."""

    return AgreeingDoubleDisclosureCommand(
        session=session,
        initiator="BANK",
        action_type="REPRICE_DEPOSIT_ACCOUNT",
        referent=referent,
        value=InterestRate(Decimal(rate)),
        sources=sources,
    )


def contest(
    referent: NodeId,
    session: int,
    a: str,
    b: str,
    sources: tuple[str, str] = ("letter", "email"),
) -> ConflictingDoubleDisclosureCommand:
    """A command in which two sources state different rates for the account."""

    return ConflictingDoubleDisclosureCommand(
        session=session,
        initiator="BANK",
        referent=referent,
        relation="hasInterestRate",
        a=InterestRate(Decimal(a)),
        b=InterestRate(Decimal(b)),
        sources=sources,
    )


def move(referent: NodeId, session: int, action_type: str) -> MutateCommand:
    """A command taking the account through a status move, naming no value."""

    return MutateCommand(
        session=session,
        initiator="BANK",
        action_type=action_type,
        source="letter",
        referent=referent,
    )


def read(entity: NodeId, session: int) -> ReadCommand:
    """A command in which the operator states the entity's current values."""

    return ReadCommand(
        session=session,
        initiator="CLIENT",
        source="operator",
        entity=entity,
    )


def disclosures_in(records: tuple[Record, ...]) -> list[Disclosure]:
    """The disclosures among the records, in order."""

    return [r for r in records if isinstance(r, Disclosure)]
