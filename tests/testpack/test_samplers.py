import random

import pytest

from mbench.core.values.samplers import draw, draw_step
from tests.testpack.pools import POOLS
from tests.testpack.samplers import (
    CHECKING,
    INIT_SAMPLERS,
    SAVINGS,
    STEP_SAMPLERS,
)
from tests.testpack.values import DepositKind, ProductName

OPEN = "OPEN_DEPOSIT_ACCOUNT"


def test_a_product_name_is_valid_exactly_when_a_product_pool_lists_it() -> None:
    pooled = {m for pool in POOLS.values() for m in pool.members}

    assert {ProductName(name) for name in ProductName.MEMBERS} == pooled


@pytest.mark.parametrize("kind", [CHECKING, SAVINGS], ids=str)
def test_every_first_value_sampler_draws_a_valid_value(
    kind: DepositKind,
) -> None:
    stream = random.Random(0)

    for (_, relation), sampler in INIT_SAMPLERS.items():
        for _ in range(50):
            value = draw(sampler, stream, pools=POOLS, values={"kind": kind})
            assert value is not None and value.is_valid(), relation


@pytest.mark.parametrize("kind", [CHECKING, SAVINGS], ids=str)
def test_every_step_sampler_moves_a_valid_value_to_another_valid_one(
    kind: DepositKind,
) -> None:
    stream = random.Random(0)
    values = {"kind": kind}

    # The account's opening values are the ones its steps start from.
    for (_, relation), sampler in STEP_SAMPLERS.items():
        first_values = INIT_SAMPLERS[(OPEN, relation)]
        for _ in range(50):
            current = draw(first_values, stream, pools=POOLS, values=values)
            assert current is not None

            nxt = draw_step(
                sampler, current, stream, pools=POOLS, values=values
            )
            assert nxt is not None and nxt.is_valid(), relation
            assert nxt != current, relation
