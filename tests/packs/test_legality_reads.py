from collections.abc import Mapping
from dataclasses import replace

import pytest

from mbench.packs.spec import EntityType, InitAction, LoadedPack, RoleFilter
from tests.core.world import (
    FEE,
    FEE_GATE,
    with_action,
    with_entity_type,
    with_fee_copy,
    with_gate,
    with_issue_gate,
    with_role_filter,
)
from tests.testpack.pack import (
    CHECKING_ACCOUNT,
    DEPOSIT_ACCOUNT,
    LOADED_PACK,
    PAYMENT_CARD,
)
from tests.testpack.values import LifecycleStatus


def _without_copy() -> LoadedPack:
    """The test pack with its one `Copy`, the replacement's, removed."""

    copying = LOADED_PACK.action_types["ISSUE_REPLACEMENT_CARD"]
    assert isinstance(copying, InitAction)

    return with_action(LOADED_PACK, replace(copying, derives={}))


def test_a_type_lists_its_status_though_nothing_else_reads_it() -> None:
    branch = EntityType(
        "BRANCH",
        relations={"hasStatus": LifecycleStatus},
        status="hasStatus",
    )
    pack = with_entity_type(LOADED_PACK, branch)

    assert pack.relations_legality_reads[branch.name] == {"hasStatus"}


def test_a_type_without_a_status_lists_nothing_of_its_own() -> None:
    branch = EntityType("BRANCH", relations={})
    pack = with_entity_type(LOADED_PACK, branch)

    assert pack.relations_legality_reads[branch.name] == frozenset()


def test_the_relations_role_filters_read_are_listed_on_their_types() -> None:
    pack = _without_copy()

    assert pack.relations_legality_reads[DEPOSIT_ACCOUNT.name] == {
        "hasStatus",
        "kind",
    }
    assert pack.relations_legality_reads[PAYMENT_CARD.name] == {
        "hasStatus",
        "hasCorrespondingAccount",
    }


def test_a_relation_an_action_gates_on_is_listed() -> None:
    pack = with_gate(LOADED_PACK, "REPRICE_DEPOSIT_ACCOUNT", FEE_GATE)

    assert FEE in pack.relations_legality_reads[DEPOSIT_ACCOUNT.name]


def test_a_relation_an_endpoint_gate_reads_is_listed_on_the_target() -> None:
    pack = with_issue_gate(LOADED_PACK, FEE_GATE)

    assert FEE in pack.relations_legality_reads[DEPOSIT_ACCOUNT.name]
    assert FEE not in pack.relations_legality_reads[PAYMENT_CARD.name]


def test_a_relation_a_role_filter_requires_is_listed() -> None:
    pack = with_role_filter(
        LOADED_PACK, RoleFilter("FEE", DEPOSIT_ACCOUNT.name, values=FEE_GATE)
    )

    assert FEE in pack.relations_legality_reads[DEPOSIT_ACCOUNT.name]


def test_a_copy_lists_its_relation_on_the_type_its_link_reaches() -> None:
    assert LOADED_PACK.derivation_reads[PAYMENT_CARD.name] == {"cardType"}
    assert LOADED_PACK.derivation_reads[DEPOSIT_ACCOUNT.name] == frozenset()


def test_a_relation_a_derivation_copies_is_listed() -> None:
    pack = with_fee_copy(LOADED_PACK)

    assert pack.derivation_reads[DEPOSIT_ACCOUNT.name] == {FEE}
    assert FEE in pack.relations_legality_reads[DEPOSIT_ACCOUNT.name]


def test_a_derivation_by_type_or_copied_link_reads_no_relation() -> None:
    # The card's `ByType` and the replacement's `CopyLink` are all that is left.
    pack = _without_copy()

    assert all(not reads for reads in pack.derivation_reads.values())


@pytest.mark.parametrize(
    "table",
    [
        LOADED_PACK.relations_legality_reads,
        LOADED_PACK.filter_reads,
        LOADED_PACK.filter_reads[CHECKING_ACCOUNT],
        LOADED_PACK.derivation_reads,
        LOADED_PACK.contestable_initiators,
        LOADED_PACK.default_sources,
    ],
    ids=[
        "legality reads",
        "filter reads",
        "one filter's reads",
        "derivation reads",
        "contestable initiators",
        "default sources",
    ],
)
def test_the_derived_tables_are_read_only(table: Mapping[str, object]) -> None:
    with pytest.raises(TypeError, match="item assignment"):
        table["anything"] = frozenset()  # type: ignore[index]
