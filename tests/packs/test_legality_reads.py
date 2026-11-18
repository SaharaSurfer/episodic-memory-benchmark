from dataclasses import replace

import pytest

from mbench.packs.spec import EntityType, RoleFilter
from tests.core.world import (
    FEE,
    FEE_GATE,
    with_entity_type,
    with_gate,
    with_issue_gate,
    with_role_filter,
)
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK, PAYMENT_CARD
from tests.testpack.values import LifecycleStatus


def test_a_type_lists_its_status_though_nothing_else_reads_it() -> None:
    branch = EntityType(
        "BRANCH",
        relations={"hasStatus": LifecycleStatus},
        status="hasStatus",
    )
    pack = with_entity_type(LOADED_PACK, branch)

    assert pack.relations_legality_reads(branch.name) == {"hasStatus"}


def test_a_type_without_a_status_lists_nothing_of_its_own() -> None:
    branch = EntityType("BRANCH", relations={})
    pack = with_entity_type(LOADED_PACK, branch)

    assert pack.relations_legality_reads(branch.name) == frozenset()


def test_the_relations_role_filters_read_are_listed_on_their_types() -> None:
    assert LOADED_PACK.relations_legality_reads(DEPOSIT_ACCOUNT.name) == {
        "hasStatus",
        "kind",
    }
    assert LOADED_PACK.relations_legality_reads(PAYMENT_CARD.name) == {
        "hasStatus",
        "hasCorrespondingAccount",
    }


def test_a_relation_an_action_gates_on_is_listed() -> None:
    pack = with_gate(LOADED_PACK, "REPRICE_DEPOSIT_ACCOUNT", FEE_GATE)

    assert FEE in pack.relations_legality_reads(DEPOSIT_ACCOUNT.name)


def test_a_relation_an_endpoint_gate_reads_is_listed_on_the_target() -> None:
    pack = with_issue_gate(LOADED_PACK, FEE_GATE)

    assert FEE in pack.relations_legality_reads(DEPOSIT_ACCOUNT.name)
    assert FEE not in pack.relations_legality_reads(PAYMENT_CARD.name)


def test_a_relation_a_role_filter_requires_is_listed() -> None:
    pack = with_role_filter(
        LOADED_PACK, RoleFilter("FEE", DEPOSIT_ACCOUNT.name, values=FEE_GATE)
    )

    assert FEE in pack.relations_legality_reads(DEPOSIT_ACCOUNT.name)


def test_a_relation_a_derivation_reads_is_listed() -> None:
    pack = replace(
        LOADED_PACK, derivation_reads={DEPOSIT_ACCOUNT.name: frozenset({FEE})}
    )

    assert FEE in pack.relations_legality_reads(DEPOSIT_ACCOUNT.name)


def test_the_derivation_reads_are_read_only() -> None:
    given = {DEPOSIT_ACCOUNT.name: frozenset({FEE})}
    reads = replace(LOADED_PACK, derivation_reads=given).derivation_reads

    with pytest.raises(TypeError, match="item assignment"):
        reads[PAYMENT_CARD.name] = frozenset()  # type: ignore[index]
