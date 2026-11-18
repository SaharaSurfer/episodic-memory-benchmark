from mbench.packs.spec import MutateAction
from tests.dependency_rule import declared_names
from tests.testpack.pack import LOADED_PACK as FINANCE_SUBSET
from tests.valuegate.pack import (
    LANTERN,
    LOADED_PACK,
    LONG,
    TRIM_WICK,
    WICK_LENGTH,
)


def test_one_mutate_gates_the_one_value_of_a_type_without_status() -> None:
    mutates = [
        action
        for action in LOADED_PACK.action_types.values()
        if isinstance(action, MutateAction)
    ]

    assert list(LOADED_PACK.entity_types) == [LANTERN.name]
    assert list(LANTERN.relations) == [WICK_LENGTH]
    assert LANTERN.status is None
    assert [action.name for action in mutates] == [TRIM_WICK]
    assert mutates[0].relation == WICK_LENGTH
    assert mutates[0].gate == {WICK_LENGTH: frozenset({LONG})}


def test_the_fixture_shares_no_name_with_the_finance_subset() -> None:
    shared = declared_names(LOADED_PACK) & declared_names(FINANCE_SUBSET)

    assert shared == set()
