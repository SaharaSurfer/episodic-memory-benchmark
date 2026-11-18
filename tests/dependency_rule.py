import ast
import re
from pathlib import Path
from typing import NamedTuple

from mbench.packs.spec import LoadedPack

ALLOWED_PACK_MODULE = "spec"
WORD = re.compile(r"[A-Za-z_]\w*")


class ForbiddenImport(NamedTuple):
    importer: str
    imported: str


class WrittenName(NamedTuple):
    module: str
    name: str


def declared_names(pack: LoadedPack) -> set[str]:
    """Every name the pack declares, its value classes' tags included."""

    types = pack.entity_types.values()

    return {
        *pack.entity_types,
        *(relation for t in types for relation in t.relations),
        *(cls.tag for t in types for cls in t.relations.values()),
        *(link for t in types for link in t.links),
        *pack.action_types,
        *pack.role_filters,
        *pack.actors,
        *pack.speakers,
        *pack.sources,
        pack.owner,
    }


def pack_imports_beyond_spec(package_root: Path) -> list[ForbiddenImport]:
    """Imports outside `packs/` that reach any pack module but the spec."""

    package = package_root.name
    packs_prefix = f"{package}.packs."
    forbidden: list[ForbiddenImport] = []

    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        if relative.parts[0] == "packs":
            continue

        importer, importer_package = _module_and_package(package, relative)
        tree = ast.parse(path.read_text())

        for imported in _imported_modules(tree, importer_package):
            if not imported.startswith(packs_prefix):
                continue

            pack_module = imported.removeprefix(packs_prefix).split(".")[0]
            if pack_module != ALLOWED_PACK_MODULE:
                forbidden.append(ForbiddenImport(importer, imported))

    return forbidden


def pack_names_written(
    package_root: Path, names: set[str]
) -> list[WrittenName]:
    """The names as whole words in modules outside the concrete packs."""

    written: list[WrittenName] = []

    # Reading the text, not the syntax tree, finds a name wherever it is
    # written: an identifier, an attribute, inside a string or in a comment.
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        if relative.parts[0] == "packs" and len(relative.parts) > 2:
            continue

        module, _ = _module_and_package(package_root.name, relative)
        words = WORD.findall(path.read_text())
        written.extend(WrittenName(module, w) for w in words if w in names)

    return written


def _module_and_package(package: str, relative: Path) -> tuple[str, list[str]]:
    """Dotted module name, and the package its relative imports resolve from."""

    parts = [package, *relative.with_suffix("").parts]

    if parts[-1] == "__init__":
        parts.pop()
        return ".".join(parts), parts

    return ".".join(parts), parts[:-1]


def _imported_modules(tree: ast.Module, package: list[str]) -> list[str]:
    """Every module the tree imports, made absolute, in source order."""

    statements = (n for n in ast.walk(tree) if isinstance(n, ast.stmt))
    in_line_order = sorted(statements, key=lambda n: (n.lineno, n.col_offset))
    modules: list[str] = []

    for node in in_line_order:
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_module(node, package)

            # `from a import b` may import the submodule `a.b`.
            modules.extend(f"{base}.{alias.name}" for alias in node.names)

    return modules


def _absolute_module(node: ast.ImportFrom, package: list[str]) -> str:
    """Full dotted name of the module a `from` import names."""

    if node.level == 0:
        return node.module or ""

    anchor = package[: len(package) - node.level + 1]
    return ".".join([*anchor, *filter(None, [node.module])])
