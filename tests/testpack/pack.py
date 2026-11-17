from mbench.packs.spec import (
    Actor,
    EntityType,
    InitAction,
    LoadedPack,
    MutateAction,
    Source,
    SourceKind,
    Speaker,
)
from tests.testpack.values import (
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
)


def _status_move(name: str, sources: set[str], target: str) -> MutateAction:
    """A deposit account's status action, gated on its source statuses."""

    return MutateAction(
        name,
        referent_type=DEPOSIT_ACCOUNT.name,
        relation="hasStatus",
        gate={"hasStatus": frozenset(map(LifecycleStatus, sources))},
        fixes=LifecycleStatus(target),
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

LOADED_PACK = LoadedPack(
    entity_types={DEPOSIT_ACCOUNT.name: DEPOSIT_ACCOUNT},
    action_types={
        "OPEN_DEPOSIT_ACCOUNT": InitAction(
            "OPEN_DEPOSIT_ACCOUNT", referent_type=DEPOSIT_ACCOUNT.name
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
        **{
            action.name: action
            for action in (
                _status_move("FREEZE_DEPOSIT_ACCOUNT", {"active"}, "frozen"),
                _status_move("UNFREEZE_DEPOSIT_ACCOUNT", {"frozen"}, "active"),
                _status_move(
                    "CLOSE_DEPOSIT_ACCOUNT", {"active", "frozen"}, "closed"
                ),
            )
        },
    },
    actors={actor.name: actor for actor in (CLIENT, BANK)},
    speakers={speaker.id: speaker for speaker in SPEAKERS},
    sources={source.id: source for source in SOURCES},
    owner=CLIENT.name,
)
