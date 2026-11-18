from mbench.packs.spec import (
    Actor,
    EntityType,
    InitAction,
    Linker,
    LoadedPack,
    MutateAction,
    RoleFilter,
    Source,
    SourceKind,
    Speaker,
)
from tests.testpack.values import (
    CardType,
    DepositKind,
    InterestRate,
    LastFour,
    LifecycleStatus,
    MonetaryAmount,
    ProductName,
)

DEPOSIT_ACCOUNT = EntityType(
    "DEPOSIT_ACCOUNT",
    relations={
        "kind": DepositKind,
        "lastFour": LastFour,
        "productName": ProductName,
        "hasStatus": LifecycleStatus,
        "hasInterestRate": InterestRate,
        "hasMonthlyFee": MonetaryAmount,
    },
    status="hasStatus",
    terminal=frozenset({LifecycleStatus("closed")}),
    anchor=("kind", "lastFour"),
    nameable=True,
)

PAYMENT_CARD = EntityType(
    "PAYMENT_CARD",
    relations={
        "cardType": CardType,
        "lastFour": LastFour,
        "hasStatus": LifecycleStatus,
    },
    status="hasStatus",
    terminal=frozenset({LifecycleStatus("closed")}),
    links={"hasCorrespondingAccount": frozenset({DEPOSIT_ACCOUNT.name})},
    anchor=("cardType", "lastFour"),
    nameable=True,
)


def _status_move(
    entity_type: EntityType, name: str, sources: set[str], target: str
) -> MutateAction:
    """A status action of the type, gated on its source statuses."""

    return MutateAction(
        name,
        referent_type=entity_type.name,
        relation="hasStatus",
        gate={"hasStatus": frozenset(map(LifecycleStatus, sources))},
        fixes=LifecycleStatus(target),
    )


STATUS_MOVES = (
    _status_move(
        DEPOSIT_ACCOUNT, "FREEZE_DEPOSIT_ACCOUNT", {"active"}, "frozen"
    ),
    _status_move(
        DEPOSIT_ACCOUNT, "UNFREEZE_DEPOSIT_ACCOUNT", {"frozen"}, "active"
    ),
    _status_move(
        DEPOSIT_ACCOUNT, "CLOSE_DEPOSIT_ACCOUNT", {"active", "frozen"}, "closed"
    ),
    _status_move(PAYMENT_CARD, "ACTIVATE_CARD", {"inactive"}, "active"),
    _status_move(PAYMENT_CARD, "LOCK_CARD", {"active"}, "locked"),
    _status_move(PAYMENT_CARD, "UNLOCK_CARD", {"locked"}, "active"),
    _status_move(
        PAYMENT_CARD, "CLOSE_CARD", {"inactive", "active", "locked"}, "closed"
    ),
)


CLIENT = Actor("CLIENT")
BANK = Actor("BANK")

SPEAKERS = (
    Speaker("customer", represents=CLIENT.name),
    Speaker("operator", represents=BANK.name),
)

# The four documents tie, so a conflict is two of them, never a speaker.
SOURCES = (
    Source("customer", SourceKind.SPEAKER, authority=1),
    Source("app_notification", SourceKind.DOCUMENT, authority=2),
    Source("email", SourceKind.DOCUMENT, authority=2),
    Source("letter", SourceKind.DOCUMENT, authority=2),
    Source("statement", SourceKind.DOCUMENT, authority=2),
    Source("operator", SourceKind.SPEAKER, authority=3),
)

CHECKING_ACCOUNT = "CHECKING_ACCOUNT"
LIVE_ACCOUNT = "LIVE_ACCOUNT"
NO_LIVE_CARD = "NO_LIVE_CARD"
CARD_ELIGIBLE_ACCOUNT = "CARD_ELIGIBLE_ACCOUNT"

_CHECKING_ONLY = {"kind": frozenset({DepositKind("checking")})}
_CARD_ON_ACCOUNT = Linker(PAYMENT_CARD.name, "hasCorrespondingAccount")

ROLE_FILTERS = (
    RoleFilter(
        CHECKING_ACCOUNT,
        DEPOSIT_ACCOUNT.name,
        values=_CHECKING_ONLY,
    ),
    RoleFilter(LIVE_ACCOUNT, DEPOSIT_ACCOUNT.name, live=True),
    RoleFilter(
        NO_LIVE_CARD, DEPOSIT_ACCOUNT.name, no_live_linkers=(_CARD_ON_ACCOUNT,)
    ),
    # What a debit card asks of its account: all three conditions at once.
    RoleFilter(
        CARD_ELIGIBLE_ACCOUNT,
        DEPOSIT_ACCOUNT.name,
        values=_CHECKING_ONLY,
        live=True,
        no_live_linkers=(_CARD_ON_ACCOUNT,),
    ),
)

LOADED_PACK = LoadedPack(
    entity_types={
        entity_type.name: entity_type
        for entity_type in (DEPOSIT_ACCOUNT, PAYMENT_CARD)
    },
    action_types={
        "OPEN_DEPOSIT_ACCOUNT": InitAction(
            "OPEN_DEPOSIT_ACCOUNT", referent_type=DEPOSIT_ACCOUNT.name
        ),
        # The account a card draws on can be any deposit account, so its
        # endpoint has no gate.
        "ISSUE_CARD": InitAction(
            "ISSUE_CARD",
            referent_type=PAYMENT_CARD.name,
            links={"hasCorrespondingAccount": {}},
        ),
        "REPRICE_DEPOSIT_ACCOUNT": MutateAction(
            "REPRICE_DEPOSIT_ACCOUNT",
            referent_type=DEPOSIT_ACCOUNT.name,
            relation="hasInterestRate",
        ),
        "CHANGE_ACCOUNT_FEE": MutateAction(
            "CHANGE_ACCOUNT_FEE",
            referent_type=DEPOSIT_ACCOUNT.name,
            relation="hasMonthlyFee",
        ),
        **{action.name: action for action in STATUS_MOVES},
    },
    actors={actor.name: actor for actor in (CLIENT, BANK)},
    speakers={speaker.id: speaker for speaker in SPEAKERS},
    sources={source.id: source for source in SOURCES},
    owner=CLIENT.name,
    role_filters={
        role_filter.name: role_filter for role_filter in ROLE_FILTERS
    },
)
