import copy
import random
import re
from itertools import pairwise

from mbench.core.records.ids import IdAllocator, NodeId

ID_SHAPE = re.compile(r"[a-z0-9]{5}")


def _allocate_many(allocator: IdAllocator, count: int) -> list[NodeId]:
    return [allocator.allocate() for _ in range(count)]


def test_an_id_is_five_characters_over_lowercase_letters_and_digits() -> None:
    ids = _allocate_many(IdAllocator(seed=7), 1000)

    assert all(ID_SHAPE.fullmatch(node_id) for node_id in ids)


def test_ids_carry_no_order_of_allocation() -> None:
    ids = _allocate_many(IdAllocator(seed=7), 1000)
    rises = sum(later > earlier for earlier, later in pairwise(ids))

    # Unordered ids rise from one to the next about half the time.
    assert 400 < rises < 600


def test_the_same_seed_gives_the_same_ids() -> None:
    assert _allocate_many(IdAllocator(seed=42), 50) == _allocate_many(
        IdAllocator(seed=42), 50
    )


def test_different_seeds_give_different_ids() -> None:
    assert _allocate_many(IdAllocator(seed=1), 50) != _allocate_many(
        IdAllocator(seed=2), 50
    )


def test_an_allocator_never_returns_an_id_already_used() -> None:
    used = set(_allocate_many(IdAllocator(seed=3), 200))
    ids = _allocate_many(IdAllocator(seed=3, used=used), 10_000)

    assert used.isdisjoint(ids)
    assert len(set(ids)) == len(ids)


def test_a_clash_is_redrawn_from_the_same_stream() -> None:
    plain = _allocate_many(IdAllocator(seed=13), 5)
    allocator = IdAllocator(seed=13, used={plain[0]})

    assert _allocate_many(allocator, 4) == plain[1:]


def test_the_used_set_passed_in_is_not_changed() -> None:
    used = {NodeId("aaaaa")}
    IdAllocator(seed=17, used=used).allocate()

    assert used == {NodeId("aaaaa")}


def test_a_second_allocator_does_not_shift_the_ids() -> None:
    expected = _allocate_many(IdAllocator(seed=23), 20)

    allocator = IdAllocator(seed=23)
    neighbour = IdAllocator(seed=23)
    ids = []
    for _ in range(20):
        neighbour.allocate()
        ids.append(allocator.allocate())

    assert ids == expected


def test_the_global_random_state_does_not_shift_the_ids() -> None:
    expected = _allocate_many(IdAllocator(seed=29), 20)

    allocator = IdAllocator(seed=29)
    ids = []
    for _ in range(20):
        random.random()
        ids.append(allocator.allocate())

    assert ids == expected


def test_a_copy_draws_what_the_original_would_have_drawn_next() -> None:
    original = IdAllocator(seed=31)
    _allocate_many(original, 5)

    duplicate = copy.copy(original)

    assert _allocate_many(duplicate, 20) == _allocate_many(original, 20)


def test_a_copy_keeps_the_ids_already_used() -> None:
    plain = _allocate_many(IdAllocator(seed=13), 2)
    original = IdAllocator(seed=13, used={plain[0]})

    assert copy.copy(original).allocate() == plain[1]


def test_drawing_from_the_original_leaves_a_copy_sequence_alone() -> None:
    expected = _allocate_many(IdAllocator(seed=41), 20)
    original = IdAllocator(seed=41)
    duplicate = copy.copy(original)

    _allocate_many(original, 10)

    assert _allocate_many(duplicate, 20) == expected


def test_an_id_a_copy_used_is_not_used_in_the_original() -> None:
    original = IdAllocator(seed=43)
    used_by_copy = copy.copy(original).allocate()

    # Had the used set been shared, the original would skip this id.
    assert original.allocate() == used_by_copy
