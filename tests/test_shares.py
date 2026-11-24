import pytest

from app.services.shares import distribute_shares


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, []),
        (1, [100]),
        (2, [50, 50]),
        (3, [34, 33, 33]),
        (7, [15, 15, 14, 14, 14, 14, 14]),
        (100, [1] * 100),
    ],
)
def test_distribute_shares(count: int, expected: list[int]) -> None:
    assert distribute_shares(count) == expected


@pytest.mark.parametrize("count", range(1, 101))
def test_shares_always_sum_to_100_and_differ_by_at_most_one(count: int) -> None:
    shares = distribute_shares(count)
    assert len(shares) == count
    assert sum(shares) == 100
    assert max(shares) - min(shares) <= 1
    assert shares == sorted(shares, reverse=True)  # remainder goes to the first offers


def test_more_offers_than_points_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        distribute_shares(101)


def test_negative_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        distribute_shares(-1)


def test_custom_total() -> None:
    assert distribute_shares(3, total=10) == [4, 3, 3]
