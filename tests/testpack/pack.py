from mbench.packs.spec import EntityType, InitAction, LoadedPack
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
            "OPEN_DEPOSIT_ACCOUNT", creates=DEPOSIT_ACCOUNT.name
        ),
    },
)
