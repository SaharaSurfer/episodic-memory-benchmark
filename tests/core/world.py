from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import ClassVar, Self

from mbench.core.folds.graph import Graph, fold_trace
from mbench.core.folds.registry import Registry
from mbench.core.legality.predicate import Refusal
from mbench.core.log_builder import LogBuilder
from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    Command,
    ConflictingDoubleDisclosureCommand,
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.core.records.ids import NodeId
from mbench.core.records.log import (
    AcceptedCommand,
    Disclosure,
    InitEvent,
    Log,
    Record,
)
from mbench.core.values.protocol import ValueClass, Zone, ZonedValueClass
from mbench.packs.spec import (
    Copy,
    EntityType,
    Framing,
    Gate,
    InitAction,
    LoadedPack,
    MutateAction,
    RoleFilter,
)
from tests.core.records.handmade import OPEN_ACCOUNT
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import (
    ACTIVE,
    INACTIVE,
    OPEN,
    CaseKind,
    DepositKind,
    InterestRate,
    LastFour,
    LifecycleStatus,
    MonetaryAmount,
    ProductName,
    ReferenceNumber,
)

OPENED_IN = 1
OPENING_RATE = "4.25"
ISSUED_IN = 2
REPORTED_IN = 3
REPLACED_IN = 4
CARD_LINK = "hasCorrespondingAccount"
REPLACES = "replaces"
CASE_LINK = "isAbout"
FEE = "hasMonthlyFee"

# A gate reading a relation nothing else reads.
FEE_GATE: Gate = {FEE: frozenset({MonetaryAmount(Decimal("5"))})}

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

# Read-only for the same reason. The card type is left out, as the pack derives
# it from the account.
CARD_WRITES: Mapping[str, ValueClass] = MappingProxyType(
    {
        "lastFour": LastFour("9012"),
        "hasStatus": INACTIVE,
    }
)

# Read-only for the same reason. Its last four differ from CARD_WRITES', so a
# replacement, sharing its card's type, keeps an anchor of its own.
REPLACEMENT_WRITES: Mapping[str, ValueClass] = MappingProxyType(
    {
        "lastFour": LastFour("5577"),
        "hasStatus": INACTIVE,
    }
)

# Read-only for the same reason. The kind is the one `REPORT_FRAUD` fixes.
CASE_WRITES: Mapping[str, ValueClass] = MappingProxyType(
    {
        "kind": CaseKind("fraud_report"),
        "caseNumber": ReferenceNumber("48213"),
        "hasStatus": OPEN,
    }
)


class World:
    """A log built one accepted command at a time."""

    def __init__(self, pack: LoadedPack = LOADED_PACK) -> None:
        """Start an empty log over the pack."""

        self.pack = pack
        self._builder = LogBuilder(pack, id_seed=0)
        self.opened_count = 0

    @property
    def log(self) -> Log:
        """The log so far."""

        return self._builder.log

    @property
    def records(self) -> tuple[Record, ...]:
        """The log's records so far, in order."""

        return self.log.records

    @property
    def registry(self) -> Registry:
        """The registry at the end of the log so far."""

        return self._builder.registry

    @property
    def graph(self) -> Graph:
        """The graph folded from the log so far."""

        return fold_trace(self.records, self.pack)

    def decide(self, command: Command) -> AcceptedCommand | Refusal:
        """Decide the command against the log so far, appending nothing."""

        return self._builder.dry_run().decide(command)

    def accept(self, command: Command) -> tuple[Record, ...]:
        """Decide the command, append it to the log and give its records."""

        run = self._builder.dry_run()
        outcome = run.decide(command)
        assert not isinstance(outcome, Refusal)

        self._builder.commit(run)
        return outcome.records

    def open(self, **changes: ValueClass) -> NodeId:
        """Open an account in the first session, and give its id."""

        changes = {"lastFour": self._next_last_four(), **changes}

        return created_id(self.accept(open_account(OPENED_IN, **changes)))

    def open_lacking(self, *relations: str) -> NodeId:
        """Open an account without the relations, and give its id."""

        command = opening_lacking(
            OPENED_IN, *relations, lastFour=self._next_last_four()
        )

        return created_id(self.accept(command))

    def issue_card(self, account: NodeId) -> NodeId:
        """Issue a card on the account in the second session, give its id."""

        return created_id(self.accept(issue(account, ISSUED_IN)))

    def replace_card(self, card: NodeId) -> NodeId:
        """Issue a replacement of the card, and give its id."""

        return created_id(self.accept(replacement(card, REPLACED_IN)))

    def open_case(self, card: NodeId | None = None) -> NodeId:
        """Report fraud on the card, else a new one, give the case's id."""

        about = self.issue_card(self.open()) if card is None else card

        return created_id(self.accept(report_fraud(about, REPORTED_IN)))

    def _next_last_four(self) -> LastFour:
        """The last four no account of this world has taken yet."""

        assert self.opened_count < len(LAST_FOURS), (
            "every last four is taken: add another to LAST_FOURS"
        )
        last_four = LastFour(LAST_FOURS[self.opened_count])

        self.opened_count += 1
        return last_four


def created_id(records: tuple[Record, ...]) -> NodeId:
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


def unfilled_opening(session: int = OPENED_IN) -> InitCommand:
    """A command opening an account, no value of it chosen yet."""

    return replace(open_account(session), writes={})


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


def unfilled_card(account: NodeId) -> InitCommand:
    """A command issuing a card on the account, no value chosen yet."""

    return replace(issue(account, ISSUED_IN), writes={})


def replacement(card: NodeId, session: int) -> InitCommand:
    """A command issuing a replacement of the card."""

    return InitCommand(
        session=session,
        initiator="BANK",
        action_type="ISSUE_REPLACEMENT_CARD",
        source="operator",
        writes=REPLACEMENT_WRITES,
        links={REPLACES: card},
    )


def report_fraud(
    about: NodeId, session: int, **changes: ValueClass
) -> InitCommand:
    """A command opening a fraud case about the entity."""

    return InitCommand(
        session=session,
        initiator="CLIENT",
        action_type="REPORT_FRAUD",
        source="operator",
        writes={**CASE_WRITES, **changes},
        links={CASE_LINK: about},
    )


def request_card(
    about: NodeId, session: int, **changes: ValueClass
) -> InitCommand:
    """A command opening a card request case about the entity."""

    command = report_fraud(
        about, session, **{"kind": CaseKind("card_request"), **changes}
    )

    return replace(command, action_type="REQUEST_CARD")


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


def unfilled_fee_change(
    account: NodeId, session: int = ISSUED_IN
) -> MutateCommand:
    """A command changing the account's fee, the new fee not chosen yet."""

    return replace(change_fee(account, session, "0"), value=None)


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


def fee_contest(
    referent: NodeId, session: int
) -> ConflictingDoubleDisclosureCommand:
    """A command in which two sources state different monthly fees."""

    return ConflictingDoubleDisclosureCommand(
        session=session,
        initiator="BANK",
        referent=referent,
        relation="hasMonthlyFee",
        a=MonetaryAmount(Decimal("7")),
        b=MonetaryAmount(Decimal("9")),
        sources=("letter", "email"),
    )


def status_contest(
    referent: NodeId, session: int, a: LifecycleStatus, b: LifecycleStatus
) -> ConflictingDoubleDisclosureCommand:
    """A command in which two documents state different statuses."""

    return ConflictingDoubleDisclosureCommand(
        session=session,
        initiator="BANK",
        referent=referent,
        relation="hasStatus",
        a=a,
        b=b,
        sources=("letter", "email"),
    )


def with_framings(**framings: tuple[Framing, ...]) -> LoadedPack:
    """The test pack with the named ActionTypes' framings replaced."""

    return replace(LOADED_PACK, framings={**LOADED_PACK.framings, **framings})


# Closing an account is the client's own act, so a pack must give it a step
# the bank's letter states before a status conflict can include it.
BANK_MAY_CLOSE = with_framings(
    CLOSE_DEPOSIT_ACCOUNT=(Framing("BANK", "letter"),)
)


def with_gate(pack: LoadedPack, name: str, gate: Gate) -> LoadedPack:
    """The pack with the named ActionType's gate extended."""

    action = pack.action_types[name]
    assert isinstance(action, MutateAction)
    gated = replace(action, gate={**action.gate, **gate})

    return replace(pack, action_types={**pack.action_types, name: gated})


def with_issue_gate(pack: LoadedPack, gate: Gate) -> LoadedPack:
    """The pack with the gate on a card's account extended."""

    action = pack.action_types["ISSUE_CARD"]
    assert isinstance(action, InitAction)
    extended = {**action.links[CARD_LINK], **gate}

    return with_action(
        pack, replace(action, links={**action.links, CARD_LINK: extended})
    )


def with_action(
    pack: LoadedPack, action: InitAction | MutateAction
) -> LoadedPack:
    """The pack with the ActionType added, or replacing its namesake."""

    return replace(
        pack, action_types={**pack.action_types, action.name: action}
    )


def with_fee_copy(pack: LoadedPack) -> LoadedPack:
    """The pack with a card issued at its account's monthly fee."""

    card = pack.entity_types["PAYMENT_CARD"]
    issue = pack.action_types["ISSUE_CARD"]
    assert isinstance(issue, InitAction)
    pack = with_entity_type(
        pack, replace(card, relations={**card.relations, FEE: MonetaryAmount})
    )

    return with_action(
        pack,
        replace(issue, derives={**issue.derives, FEE: Copy(CARD_LINK, FEE)}),
    )


def with_entity_type(pack: LoadedPack, entity_type: EntityType) -> LoadedPack:
    """The pack with the type added, or replacing its namesake."""

    return replace(
        pack,
        entity_types={**pack.entity_types, entity_type.name: entity_type},
    )


def with_role_filter(pack: LoadedPack, role_filter: RoleFilter) -> LoadedPack:
    """The pack with the role filter added, or replacing its namesake."""

    return replace(
        pack,
        role_filters={**pack.role_filters, role_filter.name: role_filter},
    )


@dataclass(frozen=True)
class BranchName(ZonedValueClass):
    """A name without a uniqueness scope, the same zone ignoring case."""

    tag: ClassVar[str] = "branch_name"
    payload: str

    def is_valid(self) -> bool:
        """Any name."""

        return True

    def render(self) -> str:
        """The name as spelled."""

        return self.payload

    def zone(self, other: Self) -> Zone:
        """Same if the names differ at most in case, far otherwise."""

        same = other.payload.casefold() == self.payload.casefold()

        return Zone.SAME if same else Zone.FAR

    def near(self) -> Iterator[Self]:
        """Nothing: the near zone is empty."""

        yield from ()


OPEN_BRANCH = "OPEN_BRANCH"
RECODE_BRANCH = MutateAction(
    "RECODE_BRANCH", referent_type="BRANCH", relation="code"
)

# Anchored on a class with no scope, so only the anchor rule can redraw it.
# Its codes are identifiers outside the anchor, so a MUTATE may write them.
BRANCH_PACK = replace(
    with_action(
        with_action(
            with_entity_type(
                LOADED_PACK,
                EntityType(
                    "BRANCH",
                    relations={
                        "name": BranchName,
                        "code": ReferenceNumber,
                        "spareCode": ReferenceNumber,
                    },
                    anchor=("name",),
                    nameable=True,
                ),
            ),
            InitAction(OPEN_BRANCH, referent_type="BRANCH"),
        ),
        RECODE_BRANCH,
    ),
    framings={
        **LOADED_PACK.framings,
        RECODE_BRANCH.name: (Framing("BANK", "letter"),),
    },
)


def open_branch(session: int = OPENED_IN, **writes: ValueClass) -> InitCommand:
    """A command opening a branch with these values."""

    return InitCommand(
        session=session,
        initiator="BANK",
        action_type=OPEN_BRANCH,
        source="operator",
        writes=writes,
    )


def move(referent: NodeId, session: int, action_type: str) -> MutateCommand:
    """A command taking the entity through a status move, naming no value."""

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
