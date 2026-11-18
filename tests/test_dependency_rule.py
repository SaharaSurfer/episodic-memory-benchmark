from pathlib import Path

import pytest

from mbench.packs.spec import (
    Actor,
    EntityType,
    InitAction,
    LoadedPack,
    RoleFilter,
    Source,
    SourceKind,
    Speaker,
)
from tests.dependency_rule import (
    ForbiddenImport,
    WrittenName,
    declared_names,
    pack_imports_beyond_spec,
    pack_names_written,
)
from tests.testpack.pack import LOADED_PACK as FINANCE_SUBSET
from tests.valuegate.pack import LOADED_PACK as VALUE_GATE_FIXTURE
from tests.valuegate.pack import WickLength

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "mbench"


def _write(root: Path, relative: str, source: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


def _package(tmp_path: Path, core_source: str) -> Path:
    root = tmp_path / "mbench"
    _write(root, "__init__.py")
    _write(root, "core/__init__.py")
    _write(root, "core/legality.py", core_source)
    _write(root, "packs/__init__.py")
    _write(root, "packs/spec.py")
    _write(root, "packs/finance/__init__.py")
    return root


def test_outside_packs_the_package_imports_only_the_pack_spec() -> None:
    assert pack_imports_beyond_spec(PACKAGE_ROOT) == []


def test_an_absolute_import_of_a_concrete_pack_is_reported(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, "import mbench.packs.finance\n")

    assert pack_imports_beyond_spec(root) == [
        ForbiddenImport("mbench.core.legality", "mbench.packs.finance")
    ]


def test_importing_a_concrete_pack_from_packs_is_reported(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, "from mbench.packs import finance\n")

    assert pack_imports_beyond_spec(root) == [
        ForbiddenImport("mbench.core.legality", "mbench.packs.finance")
    ]


def test_a_relative_import_of_a_concrete_pack_is_reported(
    tmp_path: Path,
) -> None:
    root = _package(
        tmp_path,
        "from ..packs.finance import types\nfrom ..packs import finance\n",
    )

    assert pack_imports_beyond_spec(root) == [
        ForbiddenImport("mbench.core.legality", "mbench.packs.finance.types"),
        ForbiddenImport("mbench.core.legality", "mbench.packs.finance"),
    ]


def test_a_relative_import_in_a_package_init_is_reported(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, "")
    _write(root, "core/__init__.py", "from ..packs.finance import types\n")

    assert pack_imports_beyond_spec(root) == [
        ForbiddenImport("mbench.core", "mbench.packs.finance.types")
    ]


def test_an_import_nested_in_a_function_is_reported(tmp_path: Path) -> None:
    root = _package(
        tmp_path, "def f() -> None:\n    import mbench.packs.finance\n"
    )

    assert pack_imports_beyond_spec(root) == [
        ForbiddenImport("mbench.core.legality", "mbench.packs.finance")
    ]


def test_importing_the_pack_spec_is_allowed(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        "from mbench.packs.spec import LoadedPack\n"
        "from ..packs import spec\n"
        "import mbench.packs\n",
    )

    assert pack_imports_beyond_spec(root) == []


def test_a_concrete_pack_may_import_itself(tmp_path: Path) -> None:
    root = _package(tmp_path, "")
    _write(root, "packs/finance/pack.py", "from mbench.packs import finance\n")

    assert pack_imports_beyond_spec(root) == []


def test_importing_pack_code_other_than_the_spec_is_reported(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, "from mbench.packs import loader, checks\n")

    assert pack_imports_beyond_spec(root) == [
        ForbiddenImport("mbench.core.legality", "mbench.packs.loader"),
        ForbiddenImport("mbench.core.legality", "mbench.packs.checks"),
    ]


def test_every_kind_of_name_a_pack_declares_is_listed() -> None:
    lamp = EntityType(
        "LAMP",
        relations={"wickLength": WickLength},
        links={"hangsFrom": frozenset({"LAMP"})},
    )
    pack = LoadedPack(
        entity_types={lamp.name: lamp},
        action_types={"HANG_LAMP": InitAction("HANG_LAMP", lamp.name)},
        actors={"KEEPER": Actor("KEEPER")},
        speakers={"guide": Speaker("guide", represents="KEEPER")},
        sources={
            "guide": Source("guide", SourceKind.SPEAKER, authority=1),
            "lamp_log": Source("lamp_log", SourceKind.DOCUMENT, authority=1),
        },
        owner="VISITOR",
        role_filters={"LIT_LAMP": RoleFilter("LIT_LAMP", lamp.name)},
    )

    assert declared_names(pack) == {
        "LAMP",
        "wickLength",
        "wick_length",
        "hangsFrom",
        "HANG_LAMP",
        "KEEPER",
        "guide",
        "lamp_log",
        "VISITOR",
        "LIT_LAMP",
    }


@pytest.mark.parametrize(
    "source",
    [
        "LANTERN = 1\n",
        "def f(x):\n    return x.LANTERN\n",
        'X = "LANTERN"\n',
        'X = "no such LANTERN here"\n',
        "# the LANTERN\n",
    ],
    ids=["identifier", "attribute", "string", "inside_a_string", "comment"],
)
def test_a_pack_name_is_reported_however_it_is_written(
    tmp_path: Path, source: str
) -> None:
    root = _package(tmp_path, source)

    assert pack_names_written(root, {"LANTERN"}) == [
        WrittenName("mbench.core.legality", "LANTERN")
    ]


def test_a_pack_name_in_the_pack_spec_is_reported(tmp_path: Path) -> None:
    root = _package(tmp_path, "")
    _write(root, "packs/spec.py", "LANTERN = 1\n")

    assert pack_names_written(root, {"LANTERN"}) == [
        WrittenName("mbench.packs.spec", "LANTERN")
    ]


def test_a_concrete_pack_may_write_its_own_names(tmp_path: Path) -> None:
    root = _package(tmp_path, "")
    _write(root, "packs/finance/pack.py", "LANTERN = 1\n")

    assert pack_names_written(root, {"LANTERN"}) == []


def test_a_word_merely_containing_a_pack_name_is_not_reported(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, "LANTERNS = 1\n")

    assert pack_names_written(root, {"LANTERN"}) == []


def _distinctive_test_pack_names() -> set[str]:
    names = declared_names(FINANCE_SUBSET) | declared_names(VALUE_GATE_FIXTURE)

    # A plain word such as "kind" or "email" can mean anything in other code,
    # so finding one there says nothing about knowing the pack.
    return {n for n in names if not (n.isalpha() and n.islower())}


def test_no_test_pack_name_is_written_outside_a_concrete_pack() -> None:
    names = _distinctive_test_pack_names()

    assert pack_names_written(PACKAGE_ROOT, names) == []
