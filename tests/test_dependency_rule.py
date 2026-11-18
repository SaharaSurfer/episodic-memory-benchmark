import ast
from pathlib import Path

from tests.dependency_rule import ForbiddenImport, pack_imports_beyond_spec
from tests.testpack.pack import LOADED_PACK

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


def _distinctive_test_pack_names() -> set[str]:
    pack = LOADED_PACK
    names = {
        *pack.entity_types,
        *(r for t in pack.entity_types.values() for r in t.relations),
        *(link for t in pack.entity_types.values() for link in t.links),
        *pack.action_types,
        *pack.role_filters,
        *pack.actors,
        *pack.speakers,
        *pack.sources,
        pack.owner,
    }

    # A plain word such as "kind" or "email" can mean anything in other code,
    # so finding one there says nothing about knowing the pack.
    return {n for n in names if not (n.isalpha() and n.islower())}


def _pack_agnostic_modules() -> list[Path]:
    # A concrete pack, a subpackage of packs, spells out its own names, no
    # other module may know them.
    return [
        path
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if path.relative_to(PACKAGE_ROOT).parts[0] != "packs"
        or len(path.relative_to(PACKAGE_ROOT).parts) == 2
    ]


def test_no_test_pack_name_is_written_outside_a_concrete_pack() -> None:
    names = _distinctive_test_pack_names()
    written = [
        (path.relative_to(PACKAGE_ROOT), node.value)
        for path in _pack_agnostic_modules()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Constant) and node.value in names
    ]

    assert written == []
