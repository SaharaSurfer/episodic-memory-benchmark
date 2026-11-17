from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations

from mbench.core.values.protocol import ValueClass, Zone, ZonedValueClass


@dataclass(frozen=True)
class ClassCase[V: ValueClass]:
    """One value class with the examples the contract checks it on.

    `valid` holds pairwise distinct values. `equal_pairs` holds values
    built from different payloads that the class must still treat as
    one. Zone pairs are for classes with zones only.
    """

    cls: type[V]
    valid: Sequence[V]
    invalid: Sequence[V]
    equal_pairs: Sequence[tuple[V, V]] = ()
    near_pairs: Sequence[tuple[V, V]] = ()
    far_pairs: Sequence[tuple[V, V]] = ()

    def examples(self) -> Sequence[V]:
        """Every value the case names."""

        pairs = [*self.equal_pairs, *self.near_pairs, *self.far_pairs]
        return [*self.valid, *self.invalid, *(v for p in pairs for v in p)]


type ContractCheck = Callable[[ClassCase[ValueClass]], None]


def valid_values_are_accepted(case: ClassCase[ValueClass]) -> None:
    """Every valid example passes validation."""

    _assert_examples_are_of_the_class(case)

    refused = [v for v in case.valid if not v.is_valid()]
    assert refused == [], f"refuses a valid value: {refused}"


def invalid_values_are_refused(case: ClassCase[ValueClass]) -> None:
    """Every invalid example fails validation."""

    accepted = [v for v in case.invalid if v.is_valid()]
    assert accepted == [], f"accepts an invalid value: {accepted}"


def equality_is_canonical(case: ClassCase[ValueClass]) -> None:
    """Equal pairs are one value, distinct valid examples are not."""

    for a, b in case.equal_pairs:
        assert a == b, f"equal values compare unequal: {a}, {b}"
        assert hash(a) == hash(b), f"equal values hash differently: {a}, {b}"
        assert a.render() == b.render(), (
            f"equal values render differently: {a}, {b}"
        )

    # Without a payload in the protocol, a repeated example and an
    # __eq__ that merges values look the same from here.
    for a, b in combinations(case.valid, 2):
        assert a != b, f"valid examples compare equal: {a}, {b}"


def distinct_values_render_differently(case: ClassCase[ValueClass]) -> None:
    """No two distinct valid values render to one string."""

    for a, b in combinations(case.valid, 2):
        assert a.render() != b.render(), (
            f"distinct values render alike: {a}, {b} as {a.render()!r}"
        )


def zones_match_the_examples(case: ClassCase[ValueClass]) -> None:
    """Equal values share the same zone, listed pairs fall in their zone."""

    for value in map(_zoned, case.valid):
        assert value.zone(value) is Zone.SAME, (
            f"not in its own same zone: {value}"
        )

    for a, b in case.equal_pairs:
        assert _zoned(a).zone(_zoned(b)) is Zone.SAME, (
            f"equal values are not in one same zone: {a}, {b}"
        )

    expected = [
        *((a, b, Zone.NEAR) for a, b in case.near_pairs),
        *((a, b, Zone.FAR) for a, b in case.far_pairs),
    ]

    for a, b, zone in expected:
        za, zb = _zoned(a), _zoned(b)
        assert za.zone(zb) is zone, (
            f"zone differs from the example: {b} is {za.zone(zb)} from {a}"
        )
        assert zb.zone(za) is za.zone(zb), (
            f"zone is one-sided: {a} is {zb.zone(za)} from {b}"
        )


def near_generator_yields_only_near_values(
    case: ClassCase[ValueClass],
) -> None:
    """The near generator yields valid near values, the listed ones too."""

    # Every value is in its own same zone.
    for value in map(_zoned, case.valid):
        for near in value.near():
            assert near.is_valid(), (
                f"near generator yields an invalid value: {near} from {value}"
            )
            assert value.zone(near) is Zone.NEAR, (
                f"near generator yields a value outside the near zone: "
                f"{near} is {value.zone(near)} from {value}"
            )

    for a, b in case.near_pairs:
        assert b in set(_zoned(a).near()), (
            f"near generator misses a near value: {b} from {a}"
        )


VALUE_CHECKS: list[ContractCheck] = [
    valid_values_are_accepted,
    invalid_values_are_refused,
    equality_is_canonical,
    distinct_values_render_differently,
]
ZONE_CHECKS: list[ContractCheck] = [
    zones_match_the_examples,
    near_generator_yields_only_near_values,
]
CONTRACT_CHECKS: list[ContractCheck] = VALUE_CHECKS + ZONE_CHECKS


def checks_for(case: ClassCase[ValueClass]) -> list[ContractCheck]:
    """The checks that apply: zone checks need zones or zone examples."""

    zoned = any(isinstance(v, ZonedValueClass) for v in case.examples())
    return (
        CONTRACT_CHECKS
        if zoned or case.near_pairs or case.far_pairs
        else VALUE_CHECKS
    )


def duplicate_tags(classes: Iterable[type[ValueClass]]) -> list[str]:
    """Tags that more than one of the classes carries, sorted."""

    counts = Counter(cls.tag for cls in classes)
    return sorted(tag for tag, count in counts.items() if count > 1)


def _assert_examples_are_of_the_class(case: ClassCase[ValueClass]) -> None:
    """Every example is a value of the class under test."""

    strays = [v for v in case.examples() if type(v) is not case.cls]
    assert strays == [], f"not a value of {case.cls.__name__}: {strays}"


def _zoned(value: ValueClass) -> ZonedValueClass:
    """The value as one with zones, failing if its class has none."""

    assert isinstance(value, ZonedValueClass), f"has no zones: {value}"
    return value
