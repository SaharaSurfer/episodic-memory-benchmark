from collections.abc import Mapping
from types import MappingProxyType


def freeze[K, V](mapping: Mapping[K, V]) -> Mapping[K, V]:
    """A read-only copy, so later changes to the given map don't reach it."""

    return MappingProxyType(dict(mapping))
