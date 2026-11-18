from typing import Any

import pytest

from mbench.packs.spec import InitAction
from tests.core.world import with_action
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK, SERVICE_CASE
from tests.testpack.values import ACTIVE, CaseKind


def test_a_pack_with_an_init_fixing_nothing_is_refused() -> None:
    unfixed = InitAction("OPEN_DEPOSIT_ACCOUNT", DEPOSIT_ACCOUNT.name)

    with pytest.raises(ValueError, match="OPEN_DEPOSIT_ACCOUNT"):
        with_action(LOADED_PACK, unfixed)


def test_a_pack_with_an_init_fixing_only_another_value_is_refused() -> None:
    kind_only = InitAction(
        "REPORT_FRAUD",
        SERVICE_CASE.name,
        links={"isAbout": {}},
        fixes={"kind": CaseKind("fraud_report")},
    )

    with pytest.raises(ValueError, match="REPORT_FRAUD"):
        with_action(LOADED_PACK, kind_only)


def test_an_inits_fixed_values_are_read_only() -> None:
    action = InitAction(
        "OPEN_DEPOSIT_ACCOUNT",
        DEPOSIT_ACCOUNT.name,
        fixes={"hasStatus": ACTIVE},
    )

    with pytest.raises(TypeError, match="item assignment"):
        action.fixes["kind"] = ACTIVE  # type: ignore[index]


@pytest.mark.parametrize("table", ["pools", "init_samplers", "step_samplers"])
def test_the_value_tables_are_read_only(table: str) -> None:
    held: Any = getattr(LOADED_PACK, table)

    with pytest.raises(TypeError, match="item assignment"):
        held["key"] = None
