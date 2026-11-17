from mbench.packs.spec import EntityType, InitAction, LoadedPack, MutateAction
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
)
