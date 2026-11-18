import random
import string
from collections.abc import Iterable
from typing import NewType

NodeId = NewType("NodeId", str)

ID_ALPHABET = string.ascii_lowercase + string.digits
ID_LENGTH = 5


class IdAllocator:
    """Hands out opaque node ids for one log, never repeating a used one."""

    def __init__(self, seed: int, used: Iterable[NodeId] = ()) -> None:
        """Start a stream of its own from the seed, with ids already used."""

        # A private stream, so drawing ids shifts no other seeded draw.
        self._stream = random.Random(seed)
        self._used = set(used)

    def __copy__(self) -> "IdAllocator":
        """An independent allocator that goes on to draw the same ids."""

        # The default copy would share the stream and the used set, so a
        # candidate's draws would shift every other candidate's.
        duplicate = IdAllocator(seed=0, used=self._used)
        duplicate._stream.setstate(self._stream.getstate())

        return duplicate

    def allocate(self) -> NodeId:
        """Draw the next unused id and mark it used."""

        node_id = self._draw()
        while node_id in self._used:
            node_id = self._draw()

        self._used.add(node_id)
        return node_id

    def _draw(self) -> NodeId:
        """Draw one id from the stream, used or not."""

        return NodeId("".join(self._stream.choices(ID_ALPHABET, k=ID_LENGTH)))
