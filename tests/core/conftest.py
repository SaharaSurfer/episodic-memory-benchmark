from collections.abc import Iterator
from typing import Any

import pytest

from mbench.core.legality.replay import replay
from tests.core.world import World


@pytest.fixture(autouse=True)
def every_world_replays_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Replay the log of every World a test builds, once the test is done."""

    worlds: list[World] = []
    original_init = World.__init__

    def init_and_remember(world: World, *args: Any, **kwargs: Any) -> None:
        """Start the World as usual and keep it for the replay."""

        original_init(world, *args, **kwargs)
        worlds.append(world)

    monkeypatch.setattr(World, "__init__", init_and_remember)

    yield

    for world in worlds:
        assert replay(world.log, world.pack) is None
