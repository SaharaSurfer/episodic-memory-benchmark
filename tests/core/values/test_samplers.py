import random
from decimal import Decimal
from typing import Any

import pytest

from mbench.core.values.samplers import (
    ByValue,
    Choice,
    Range,
    Sampler,
    Step,
    draw,
    draw_step,
)
from mbench.packs.spec import Pool
from tests.testpack.values import (
    DepositKind,
    InterestRate,
    MonetaryAmount,
    ProductName,
)

CHECKING = DepositKind("checking")
SAVINGS = DepositKind("savings")
FEES = tuple(MonetaryAmount(Decimal(d)) for d in ("0", "5", "10", "12", "15"))
POOLS = {
    "checking_products": Pool(
        ProductName,
        (ProductName("Everyday Checking"), ProductName("Basic Checking")),
    ),
    "savings_products": Pool(ProductName, (ProductName("Goal Saver"),)),
}
SAVINGS_RATES = Range(
    InterestRate, Decimal("0.01"), Decimal("4.50"), Decimal("0.01")
)
RATE_STEP = Step(SAVINGS_RATES, Decimal("0.05"), Decimal("0.50"))


def _rate(text: str) -> InterestRate:
    return InterestRate(Decimal(text))


def _amount(text: str) -> MonetaryAmount:
    return MonetaryAmount(Decimal(text))


def _stream(seed: int = 0) -> random.Random:
    return random.Random(seed)


def test_a_choice_draws_only_from_its_inline_list_and_reaches_each() -> None:
    stream = _stream()
    drawn = {draw(Choice(FEES), stream) for _ in range(200)}

    assert drawn == set(FEES)


def test_a_choice_draws_from_a_pool_named_in_the_pack() -> None:
    stream = _stream()
    drawn = {
        draw(Choice("checking_products"), stream, pools=POOLS)
        for _ in range(100)
    }

    assert drawn == set(POOLS["checking_products"].members)


def test_a_choice_naming_a_missing_pool_is_an_error() -> None:
    with pytest.raises(LookupError, match="no pool named 'merchants'"):
        draw(Choice("merchants"), _stream(), pools=POOLS)


def test_a_choice_never_draws_an_option_of_zero_weight() -> None:
    sampler = Choice((CHECKING, SAVINGS), weights=(1, 0))
    stream = _stream()

    assert {draw(sampler, stream) for _ in range(100)} == {CHECKING}


def test_a_choice_follows_its_weights() -> None:
    sampler = Choice((CHECKING, SAVINGS), weights=(0.6, 0.4))
    stream = _stream()
    draws = [draw(sampler, stream) for _ in range(2000)]

    assert 1100 < draws.count(CHECKING) < 1300


def test_a_choice_left_with_only_zero_weights_cannot_draw() -> None:
    sampler = Choice((CHECKING, SAVINGS), weights=(1, 0))

    assert draw(sampler, _stream(), exclude=[CHECKING]) is None


def test_a_choice_whose_weights_do_not_match_its_options_is_an_error() -> None:
    with pytest.raises(ValueError, match="2 weights for 1 options"):
        draw(Choice("savings_products", weights=(1, 1)), _stream(), pools=POOLS)


def test_a_range_lands_only_on_its_step_and_reaches_both_ends() -> None:
    sampler = Range(
        MonetaryAmount, Decimal("500"), Decimal("2000"), Decimal("500")
    )
    stream = _stream()
    drawn = {draw(sampler, stream) for _ in range(200)}

    assert drawn == {_amount(a) for a in ("500", "1000", "1500", "2000")}


def test_a_range_whose_low_is_above_its_high_is_an_error() -> None:
    with pytest.raises(ValueError, match="low 2 is above high 1"):
        Range(MonetaryAmount, Decimal("2"), Decimal("1"), Decimal("1"))


def test_a_range_whose_span_is_not_whole_steps_stops_below_its_high() -> None:
    sampler = Range(MonetaryAmount, Decimal("0"), Decimal("1"), Decimal("0.3"))
    stream = _stream()
    drawn = {draw(sampler, stream) for _ in range(200)}

    assert drawn == {_amount(a) for a in ("0", "0.3", "0.6", "0.9")}


def test_by_value_draws_with_the_branch_for_the_value_read() -> None:
    sampler: ByValue[ProductName] = ByValue(
        "kind",
        {
            CHECKING: Choice("checking_products"),
            SAVINGS: Choice("savings_products"),
        },
    )
    stream = _stream()
    drawn = {
        draw(sampler, stream, pools=POOLS, values={"kind": SAVINGS})
        for _ in range(20)
    }

    assert drawn == {ProductName("Goal Saver")}


def test_by_value_reading_a_relation_not_yet_written_is_an_error() -> None:
    sampler: ByValue[MonetaryAmount] = ByValue("kind", {CHECKING: Choice(FEES)})

    with pytest.raises(LookupError, match="reads 'kind', which has no value"):
        draw(sampler, _stream())


def test_by_value_without_a_branch_for_the_value_read_is_an_error() -> None:
    sampler: ByValue[MonetaryAmount] = ByValue("kind", {CHECKING: Choice(FEES)})

    with pytest.raises(LookupError, match="has no branch for"):
        draw(sampler, _stream(), values={"kind": SAVINGS})


def test_a_step_moves_either_way_by_a_size_within_its_limits() -> None:
    current = _rate("1.00")
    stream = _stream()
    draws = [draw_step(RATE_STEP, current, stream) for _ in range(500)]

    gaps = {abs(r.payload - current.payload) for r in draws if r is not None}
    assert min(gaps) >= Decimal("0.05")
    assert max(gaps) <= Decimal("0.50")
    assert all(r is not None and r.is_valid() for r in draws)
    assert any(r is not None and r.payload < current.payload for r in draws)
    assert any(r is not None and r.payload > current.payload for r in draws)


def test_a_step_reaches_its_largest_size_and_both_ends_of_its_range() -> None:
    sampler = Step(
        Range(InterestRate, Decimal("1.00"), Decimal("1.20"), Decimal("0.05")),
        Decimal("0.05"),
        Decimal("0.10"),
    )
    stream = _stream()

    draws = {draw_step(sampler, _rate("1.10"), stream) for _ in range(200)}

    assert draws == {_rate(r) for r in ("1.00", "1.05", "1.15", "1.20")}


def test_a_step_at_the_bottom_of_its_range_only_moves_up() -> None:
    sampler = Step(
        Range(InterestRate, Decimal("0.00"), Decimal("0.50"), Decimal("0.01")),
        Decimal("0.05"),
        Decimal("0.50"),
    )
    stream = _stream()
    draws = [draw_step(sampler, _rate("0"), stream) for _ in range(200)]

    assert all(r is not None and r.payload >= Decimal("0.05") for r in draws)


def test_a_step_never_returns_the_current_value() -> None:
    # A one-value range leaves the current value as the only candidate.
    sampler = Step(
        Range(InterestRate, Decimal("1.00"), Decimal("1.00"), Decimal("0.01")),
        Decimal("0.00"),
        Decimal("0.50"),
    )

    assert draw_step(sampler, _rate("1.00"), _stream()) is None


def test_a_choice_as_a_step_draws_another_member_of_its_list() -> None:
    stream = _stream()
    draws = {draw_step(Choice(FEES), FEES[2], stream) for _ in range(200)}

    assert draws == set(FEES) - {FEES[2]}


def test_a_step_reads_earlier_values_through_by_value() -> None:
    sampler = ByValue(
        "kind",
        {
            CHECKING: Step(
                Range(
                    InterestRate, Decimal("0"), Decimal("0.50"), Decimal("0.01")
                ),
                Decimal("0.05"),
                Decimal("0.50"),
            ),
            SAVINGS: RATE_STEP,
        },
    )
    stream = _stream()
    draws = [
        draw_step(sampler, _rate("0.40"), stream, values={"kind": CHECKING})
        for _ in range(200)
    ]

    assert all(r is not None and r.payload <= Decimal("0.50") for r in draws)


def test_a_step_drawn_as_a_first_value_is_an_error() -> None:
    with pytest.raises(ValueError, match="a step needs the current value"):
        draw(RATE_STEP, _stream())


def test_a_choice_never_returns_an_excluded_value() -> None:
    stream = _stream()
    excluded = FEES[:3]
    draws = {draw(Choice(FEES), stream, exclude=excluded) for _ in range(200)}

    assert draws == set(FEES[3:])


def test_a_choice_with_every_option_excluded_cannot_draw() -> None:
    assert draw(Choice(FEES), _stream(), exclude=FEES) is None


def test_a_range_never_returns_an_excluded_value() -> None:
    sampler = Range(
        MonetaryAmount, Decimal("0"), Decimal("1.00"), Decimal("0.01")
    )
    excluded = [_amount(f"0.{n:02}") for n in range(0, 100, 2)]
    stream = _stream()
    draws = {draw(sampler, stream, exclude=excluded) for _ in range(2000)}

    assert draws.isdisjoint(excluded)
    assert len(draws) == 101 - len(excluded)


def test_a_range_with_every_value_excluded_cannot_draw() -> None:
    sampler = Range(MonetaryAmount, Decimal("5"), Decimal("15"), Decimal("5"))
    excluded = [_amount("5"), _amount("10"), _amount("15")]

    assert draw(sampler, _stream(), exclude=excluded) is None


def test_exclusion_compares_values_canonically() -> None:
    sampler = Range(
        InterestRate, Decimal("26.40"), Decimal("26.41"), Decimal("0.01")
    )
    stream = _stream()

    # 26.4 is the value 26.40.
    draws = {draw(sampler, stream, exclude=[_rate("26.4")]) for _ in range(50)}

    assert draws == {_rate("26.41")}


def test_exclusions_off_the_range_or_of_another_class_are_ignored() -> None:
    sampler = Range(MonetaryAmount, Decimal("5"), Decimal("10"), Decimal("5"))
    # 15 is one step past the top of the range, 20 is further off.
    excluded = [
        _amount("7.50"),
        _amount("15"),
        _amount("20"),
        _rate("5"),
        CHECKING,
    ]
    stream = _stream()

    drawn = {draw(sampler, stream, exclude=excluded) for _ in range(50)}

    assert drawn == {_amount("5"), _amount("10")}


def test_a_step_never_returns_an_excluded_value() -> None:
    stream = _stream()
    excluded = [_rate("1.05"), _rate("0.95")]
    draws = {
        draw_step(RATE_STEP, _rate("1.00"), stream, exclude=excluded)
        for _ in range(500)
    }

    assert draws.isdisjoint(excluded)


def test_a_step_with_every_candidate_excluded_cannot_draw() -> None:
    sampler = Step(
        Range(InterestRate, Decimal("1.00"), Decimal("1.10"), Decimal("0.05")),
        Decimal("0.05"),
        Decimal("0.05"),
    )

    assert (
        draw_step(
            sampler,
            _rate("1.05"),
            _stream(),
            exclude=[_rate("1.00"), _rate("1.10")],
        )
        is None
    )


def test_by_value_passes_exclusions_to_its_branch() -> None:
    sampler: ByValue[MonetaryAmount] = ByValue("kind", {CHECKING: Choice(FEES)})

    assert (
        draw(sampler, _stream(), values={"kind": CHECKING}, exclude=FEES)
        is None
    )


@pytest.mark.parametrize(
    "sampler",
    [
        Choice(FEES),
        Choice((CHECKING, SAVINGS), weights=(0.6, 0.4)),
        SAVINGS_RATES,
    ],
    ids=["choice", "weighted-choice", "range"],
)
def test_the_same_seed_gives_the_same_draws(sampler: Sampler[Any]) -> None:
    def draws(seed: int) -> list[Any]:
        stream = _stream(seed)
        return [draw(sampler, stream) for _ in range(50)]

    assert draws(11) == draws(11)
    assert draws(11) != draws(12)


def test_the_same_seed_gives_the_same_steps() -> None:
    def steps(seed: int) -> list[InterestRate | None]:
        stream = _stream(seed)
        return [draw_step(RATE_STEP, _rate("2.00"), stream) for _ in range(50)]

    assert steps(5) == steps(5)
    assert steps(5) != steps(6)
