from dataclasses import replace

from mbench.packs.spec import EntityType, Linker, RoleFilter
from tests.testpack.pack import (
    CARD_ELIGIBLE_ACCOUNT,
    CHECKING_ACCOUNT,
    LIVE_ACCOUNT,
    LOADED_PACK,
    PAYMENT_CARD,
)
from tests.testpack.values import CardType, DepositKind


def test_a_value_filter_reads_the_relation_it_requires() -> None:
    assert LOADED_PACK.relations_read(CHECKING_ACCOUNT) == {
        "DEPOSIT_ACCOUNT": {"kind"}
    }


def test_a_liveness_filter_reads_the_status() -> None:
    assert LOADED_PACK.relations_read(LIVE_ACCOUNT) == {
        "DEPOSIT_ACCOUNT": {"hasStatus"}
    }


def test_a_filter_on_linked_entities_reads_their_link_and_status() -> None:
    assert LOADED_PACK.relations_read(CARD_ELIGIBLE_ACCOUNT) == {
        "DEPOSIT_ACCOUNT": {"kind", "hasStatus"},
        "PAYMENT_CARD": {"hasCorrespondingAccount", "hasStatus"},
    }


def test_a_linker_of_the_filters_own_type_adds_to_what_it_reads() -> None:
    unreplaced = RoleFilter(
        "UNREPLACED_DEBIT_CARD",
        PAYMENT_CARD.name,
        values={"cardType": frozenset({CardType("debit")})},
        no_live_linkers=(Linker(PAYMENT_CARD.name, "replaces"),),
    )
    pack = replace(LOADED_PACK, role_filters={unreplaced.name: unreplaced})

    assert pack.relations_read(unreplaced.name) == {
        "PAYMENT_CARD": {"cardType", "replaces", "hasStatus"}
    }


def test_liveness_reads_nothing_on_a_type_without_a_status() -> None:
    branch = EntityType("BRANCH", relations={})
    pack = replace(
        LOADED_PACK,
        entity_types={branch.name: branch},
        role_filters={"OPEN": RoleFilter("OPEN", branch.name, live=True)},
    )

    assert pack.relations_read("OPEN") == {"BRANCH": frozenset()}


def test_an_any_type_filter_reads_each_type_holding_its_relations() -> None:
    any_checking = RoleFilter(
        "ANY_CHECKING",
        None,
        values={"kind": frozenset({DepositKind("checking")})},
        live=True,
    )
    pack = replace(LOADED_PACK, role_filters={any_checking.name: any_checking})

    assert pack.relations_read(any_checking.name) == {
        "DEPOSIT_ACCOUNT": {"kind", "hasStatus"},
        "PAYMENT_CARD": {"hasStatus"},
        "SERVICE_CASE": {"kind", "hasStatus"},
    }
