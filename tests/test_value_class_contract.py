from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar, Self

import pytest

from mbench.core.values.protocol import ValueClass, Zone, ZonedValueClass
from tests.value_class_contract import (
    CONTRACT_CHECKS,
    VALUE_CHECKS,
    ClassCase,
    checks_for,
    distinct_values_render_differently,
    duplicate_tags,
    equality_is_canonical,
    invalid_values_are_refused,
    near_generator_yields_only_near_values,
    valid_values_are_accepted,
    zones_match_the_examples,
)


@dataclass(frozen=True)
class Digit(ZonedValueClass):
    """A digit. Neighbours on the number line are lookalikes."""

    tag: ClassVar[str] = "digit"
    payload: int

    def is_valid(self) -> bool:
        """A digit is 0 to 9."""

        return 0 <= self.payload <= 9

    def render(self) -> str:
        """The digit as written."""

        return str(self.payload)

    def zone(self, other: Self) -> Zone:
        """Equal is same, one apart is near, anything else far."""

        gap = abs(self.payload - other.payload)
        return {0: Zone.SAME, 1: Zone.NEAR}.get(gap, Zone.FAR)

    def near(self) -> Iterator[Self]:
        """The valid neighbours."""

        for payload in (self.payload - 1, self.payload + 1):
            if 0 <= payload <= 9:
                yield type(self)(payload)


@dataclass(frozen=True)
class AcceptsAnything(Digit):
    tag: ClassVar[str] = "accepts_anything"

    def is_valid(self) -> bool:
        return True


@dataclass(frozen=True)
class RefusesEverything(Digit):
    tag: ClassVar[str] = "refuses_everything"

    def is_valid(self) -> bool:
        return False


# Not dataclasses: the decorator would replace these __eq__ and __hash__.
class EqualByIdentity(Digit):
    tag: ClassVar[str] = "equal_by_identity"

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


class HashByIdentity(Digit):
    tag: ClassVar[str] = "hash_by_identity"

    def __hash__(self) -> int:
        return id(self)


@dataclass(frozen=True)
class RendersSpelling(Digit):
    """Equal digits that may be spelled out, so they render apart."""

    tag: ClassVar[str] = "renders_spelling"
    spelling: str = field(default="", compare=False)

    def render(self) -> str:
        """The spelling if there is one, else the digit."""

        return self.spelling or str(self.payload)


@dataclass(frozen=True)
class RendersParity(Digit):
    tag: ClassVar[str] = "renders_parity"

    def render(self) -> str:
        return "even" if self.payload % 2 == 0 else "odd"


@dataclass(frozen=True)
class NotItsOwnSame(Digit):
    tag: ClassVar[str] = "not_its_own_same"

    def zone(self, other: Self) -> Zone:
        return Zone.NEAR if abs(self.payload - other.payload) == 1 else Zone.FAR


@dataclass(frozen=True)
class OneSidedZone(Digit):
    """Only the next digit up is a lookalike, not the one below."""

    tag: ClassVar[str] = "one_sided_zone"

    def zone(self, other: Self) -> Zone:
        """Same if equal, near if one up, far otherwise."""

        if other.payload == self.payload:
            return Zone.SAME
        return Zone.NEAR if other.payload == self.payload + 1 else Zone.FAR


@dataclass(frozen=True)
class ZonesByIdentity(Digit):
    """Only the very same object is in the same zone."""

    tag: ClassVar[str] = "zones_by_identity"

    def zone(self, other: Self) -> Zone:
        """Same if identical, near if one apart, far otherwise."""

        if other is self:
            return Zone.SAME
        return Zone.NEAR if abs(self.payload - other.payload) == 1 else Zone.FAR


@dataclass(frozen=True)
class NearIncludesItself(Digit):
    tag: ClassVar[str] = "near_includes_itself"

    def near(self) -> Iterator[Self]:
        yield self
        yield from super().near()


@dataclass(frozen=True)
class NearYieldsFar(Digit):
    tag: ClassVar[str] = "near_yields_far"

    def near(self) -> Iterator[Self]:
        yield from super().near()
        yield type(self)((self.payload + 5) % 10)


@dataclass(frozen=True)
class NearYieldsInvalid(Digit):
    tag: ClassVar[str] = "near_yields_invalid"

    def near(self) -> Iterator[Self]:
        yield type(self)(self.payload - 1)
        yield type(self)(self.payload + 1)


@dataclass(frozen=True)
class NearMissesTheOneAbove(Digit):
    tag: ClassVar[str] = "near_misses_the_one_above"

    def near(self) -> Iterator[Self]:
        if self.payload > 0:
            yield type(self)(self.payload - 1)


@dataclass(frozen=True)
class NoZones(ValueClass):
    """A digit with no zones at all."""

    tag: ClassVar[str] = "digit"
    payload: int

    def is_valid(self) -> bool:
        """A digit is 0 to 9."""

        return 0 <= self.payload <= 9

    def render(self) -> str:
        """The digit as written."""

        return str(self.payload)


def _case(cls: Any) -> ClassCase[Any]:
    return ClassCase(
        cls,
        valid=[cls(0), cls(3), cls(9)],
        invalid=[cls(-1), cls(10)],
        equal_pairs=[(cls(4), cls(4))],
        near_pairs=[(cls(3), cls(4))],
        far_pairs=[(cls(0), cls(9))],
    )


@pytest.mark.parametrize("check", CONTRACT_CHECKS, ids=lambda c: c.__name__)
def test_a_sound_class_passes_every_check(check: Any) -> None:
    check(_case(Digit))


def test_a_class_that_accepts_invalid_payloads_fails() -> None:
    with pytest.raises(AssertionError, match="accepts an invalid value"):
        invalid_values_are_refused(_case(AcceptsAnything))


def test_a_class_that_refuses_valid_payloads_fails() -> None:
    with pytest.raises(AssertionError, match="refuses a valid value"):
        valid_values_are_accepted(_case(RefusesEverything))


def test_an_example_of_another_class_fails() -> None:
    case = ClassCase(Digit, valid=[NoZones(1)], invalid=[])

    with pytest.raises(AssertionError, match="not a value of Digit"):
        valid_values_are_accepted(case)


def test_a_class_whose_equal_values_compare_unequal_fails() -> None:
    with pytest.raises(AssertionError, match="equal values compare unequal"):
        equality_is_canonical(_case(EqualByIdentity))


def test_a_class_whose_equal_values_hash_differently_fails() -> None:
    with pytest.raises(AssertionError, match="equal values hash differently"):
        equality_is_canonical(_case(HashByIdentity))


def test_a_class_whose_equal_values_render_differently_fails() -> None:
    case = ClassCase(
        RendersSpelling,
        valid=[],
        invalid=[],
        equal_pairs=[(RendersSpelling(4), RendersSpelling(4, "four"))],
    )

    with pytest.raises(AssertionError, match="equal values render differently"):
        equality_is_canonical(case)


def test_a_case_whose_valid_examples_repeat_a_value_fails() -> None:
    case = ClassCase(Digit, valid=[Digit(1), Digit(1)], invalid=[])

    with pytest.raises(AssertionError, match="valid examples compare equal"):
        equality_is_canonical(case)


def test_a_class_that_renders_two_values_alike_fails() -> None:
    with pytest.raises(AssertionError, match="distinct values render alike"):
        distinct_values_render_differently(_case(RendersParity))


def test_a_value_outside_its_own_same_zone_fails() -> None:
    with pytest.raises(AssertionError, match="not in its own same zone"):
        zones_match_the_examples(_case(NotItsOwnSame))


def test_equal_values_in_different_zones_fail() -> None:
    with pytest.raises(
        AssertionError, match="equal values are not in one same zone"
    ):
        zones_match_the_examples(_case(ZonesByIdentity))


def test_zone_examples_that_disagree_with_the_class_fail() -> None:
    case = ClassCase(
        Digit, valid=[], invalid=[], near_pairs=[(Digit(0), Digit(9))]
    )

    with pytest.raises(AssertionError, match="zone differs from the example"):
        zones_match_the_examples(case)


def test_a_one_sided_zone_fails() -> None:
    with pytest.raises(AssertionError, match="zone is one-sided"):
        zones_match_the_examples(_case(OneSidedZone))


def test_zone_examples_on_a_class_without_zones_fail() -> None:
    case = ClassCase(
        NoZones, valid=[], invalid=[], far_pairs=[(NoZones(0), NoZones(9))]
    )

    with pytest.raises(AssertionError, match="has no zones"):
        zones_match_the_examples(case)


def test_zone_checks_apply_to_classes_with_zones_or_zone_examples() -> None:
    plain = ClassCase(NoZones, valid=[NoZones(1)], invalid=[])
    with_pairs = ClassCase(
        NoZones, valid=[], invalid=[], far_pairs=[(NoZones(0), NoZones(9))]
    )
    zoned = ClassCase(Digit, valid=[Digit(1)], invalid=[])

    assert checks_for(plain) == VALUE_CHECKS
    assert checks_for(with_pairs) == CONTRACT_CHECKS
    assert checks_for(zoned) == CONTRACT_CHECKS


def test_a_near_generator_that_yields_the_value_itself_fails() -> None:
    with pytest.raises(AssertionError, match="outside the near zone"):
        near_generator_yields_only_near_values(_case(NearIncludesItself))


def test_a_near_generator_that_yields_a_far_value_fails() -> None:
    with pytest.raises(AssertionError, match="outside the near zone"):
        near_generator_yields_only_near_values(_case(NearYieldsFar))


def test_a_near_generator_that_yields_an_invalid_value_fails() -> None:
    with pytest.raises(AssertionError, match="yields an invalid value"):
        near_generator_yields_only_near_values(_case(NearYieldsInvalid))


def test_a_near_generator_that_misses_a_near_value_fails() -> None:
    with pytest.raises(AssertionError, match="misses a near value"):
        near_generator_yields_only_near_values(_case(NearMissesTheOneAbove))


def test_two_classes_sharing_a_tag_are_reported() -> None:
    assert duplicate_tags([Digit, NoZones, RendersParity]) == ["digit"]


def test_classes_with_their_own_tags_are_not_reported() -> None:
    assert duplicate_tags([Digit, RendersParity, AcceptsAnything]) == []
