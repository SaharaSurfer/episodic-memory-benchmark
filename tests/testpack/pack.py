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
    },
)
