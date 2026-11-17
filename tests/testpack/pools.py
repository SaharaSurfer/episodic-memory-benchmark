from collections.abc import Mapping
from typing import Any

from mbench.packs.spec import Pool
from tests.testpack.values import (
    CHECKING_PRODUCTS,
    SAVINGS_PRODUCTS,
    ProductName,
)

# The name lists in the values module are the one source: the pools
# hold them as values, and the class accepts exactly their union.
POOLS: Mapping[str, Pool[Any]] = {
    "checking_products": Pool(
        ProductName, tuple(map(ProductName, CHECKING_PRODUCTS))
    ),
    "savings_products": Pool(
        ProductName, tuple(map(ProductName, SAVINGS_PRODUCTS))
    ),
}
