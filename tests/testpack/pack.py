from mbench.packs.spec import (
    Actor,
    ByType,
    Copy,
    CopyLink,
    EntityType,
    Framing,
    InitAction,
    Linker,
    LoadedPack,
    MutateAction,
    RoleFilter,
    Source,
    SourceKind,
    Speaker,
    default_source,
)
from tests.testpack.pools import POOLS
from tests.testpack.samplers import INIT_SAMPLERS, STEP_SAMPLERS
from tests.testpack.values import (
    ACTIVE,
    INACTIVE,
    OPEN,
    CardType,
    CaseKind,
    DepositKind,
    InterestRate,
    LastFour,
    LifecycleStatus,
    MonetaryAmount,
    ProductName,
    ReferenceNumber,
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
    links={
        "hasCorrespondingAccount": frozenset({DEPOSIT_ACCOUNT.name}),
        "replaces": frozenset({"PAYMENT_CARD"}),
    },
    anchor=("cardType", "lastFour"),
    nameable=True,
)

SERVICE_CASE = EntityType(
    "SERVICE_CASE",
    relations={
        "kind": CaseKind,
        "caseNumber": ReferenceNumber,
        "hasStatus": LifecycleStatus,
    },
    status="hasStatus",
    terminal=frozenset({LifecycleStatus("closed")}),
    links={"isAbout": frozenset({PAYMENT_CARD.name, DEPOSIT_ACCOUNT.name})},
    anchor=("kind", "caseNumber"),
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
    # A denied case can be reviewed again, on appeal.
    _status_move(
        SERVICE_CASE, "REVIEW_CASE", {"open", "denied"}, "under_review"
    ),
    _status_move(SERVICE_CASE, "APPROVE_CASE", {"under_review"}, "approved"),
    _status_move(SERVICE_CASE, "DENY_CASE", {"under_review"}, "denied"),
    _status_move(
        SERVICE_CASE,
        "CLOSE_CASE",
        {"open", "under_review", "approved", "denied"},
        "closed",
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


def _framing(initiator: str, named: str | None = None) -> Framing:
    """How a step occurs: its initiator, and the source that states it."""

    return Framing(
        initiator, default_source(initiator, named, SPEAKERS, SOURCES)
    )


_CLIENT_STATES = _framing(CLIENT.name)
_BANK_STATES = _framing(BANK.name)
_BANK_WRITES = _framing(BANK.name, "letter")

# Every way each ActionType occurs in the pack's errands. One that names no
# source is stated by its initiator's speaker.
FRAMINGS = {
    "OPEN_DEPOSIT_ACCOUNT": (_CLIENT_STATES,),
    # The bank issues on its own, or the client asks and the operator says so.
    "ISSUE_CARD": (_BANK_STATES, _framing(CLIENT.name, "operator")),
    "ISSUE_REPLACEMENT_CARD": (_BANK_STATES,),
    "REPRICE_DEPOSIT_ACCOUNT": (_BANK_WRITES,),
    "CHANGE_ACCOUNT_FEE": (_BANK_WRITES,),
    "FREEZE_DEPOSIT_ACCOUNT": (_BANK_STATES,),
    "UNFREEZE_DEPOSIT_ACCOUNT": (_BANK_STATES,),
    "CLOSE_DEPOSIT_ACCOUNT": (_CLIENT_STATES,),
    "ACTIVATE_CARD": (_CLIENT_STATES,),
    # The client locks a card, or the bank does on a fraud report.
    "LOCK_CARD": (_CLIENT_STATES, _BANK_STATES),
    "UNLOCK_CARD": (_CLIENT_STATES,),
    "CLOSE_CARD": (_CLIENT_STATES,),
    # The client asks, and the operator opens the case and says so.
    "REPORT_FRAUD": (_framing(CLIENT.name, "operator"),),
    "REQUEST_CARD": (_framing(CLIENT.name, "operator"),),
    # The bank works a case, and the client can appeal a denied one.
    "REVIEW_CASE": (_BANK_STATES, _CLIENT_STATES),
    "APPROVE_CASE": (_BANK_STATES,),
    "DENY_CASE": (_BANK_STATES,),
    "CLOSE_CASE": (_BANK_STATES,),
}

LOADED_PACK = LoadedPack(
    entity_types={
        entity_type.name: entity_type
        for entity_type in (DEPOSIT_ACCOUNT, PAYMENT_CARD, SERVICE_CASE)
    },
    action_types={
        "OPEN_DEPOSIT_ACCOUNT": InitAction(
            "OPEN_DEPOSIT_ACCOUNT",
            referent_type=DEPOSIT_ACCOUNT.name,
            fixes={"hasStatus": ACTIVE},
        ),
        # The account a card draws on can be any deposit account, so its
        # endpoint has no gate.
        "ISSUE_CARD": InitAction(
            "ISSUE_CARD",
            referent_type=PAYMENT_CARD.name,
            links={"hasCorrespondingAccount": {}},
            fixes={"hasStatus": INACTIVE},
            derives={
                "cardType": ByType(
                    "hasCorrespondingAccount",
                    {DEPOSIT_ACCOUNT.name: CardType("debit")},
                )
            },
        ),
        # The card replaced may be closed, so its endpoint has no gate either.
        "ISSUE_REPLACEMENT_CARD": InitAction(
            "ISSUE_REPLACEMENT_CARD",
            referent_type=PAYMENT_CARD.name,
            links={"replaces": {}},
            fixes={"hasStatus": INACTIVE},
            derives={"cardType": Copy("replaces", "cardType")},
            copied_links={
                "hasCorrespondingAccount": CopyLink(
                    "replaces", "hasCorrespondingAccount"
                )
            },
        ),
        # What a case is about is the role filter's to narrow, if any.
        "REPORT_FRAUD": InitAction(
            "REPORT_FRAUD",
            referent_type=SERVICE_CASE.name,
            links={"isAbout": {}},
            fixes={"kind": CaseKind("fraud_report"), "hasStatus": OPEN},
        ),
        "REQUEST_CARD": InitAction(
            "REQUEST_CARD",
            referent_type=SERVICE_CASE.name,
            links={"isAbout": {}},
            fixes={"kind": CaseKind("card_request"), "hasStatus": OPEN},
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
    framings=FRAMINGS,
    derivation_reads={PAYMENT_CARD.name: frozenset({"cardType"})},
    pools=POOLS,
    init_samplers=INIT_SAMPLERS,
    step_samplers=STEP_SAMPLERS,
)
