"""Offer share distribution for a stream."""

TOTAL_SHARE = 100


def distribute_shares(count: int, total: int = TOTAL_SHARE) -> list[int]:
    """Split `total` percent evenly between `count` offers.

    The remainder of the integer division is handed out one point at a time to the
    first offers, so the result always sums to `total`:

        >>> distribute_shares(3)
        [34, 33, 33]
        >>> distribute_shares(7)
        [15, 15, 14, 14, 14, 14, 14]

    Zero offers give an empty list. More offers than `total` points cannot all get a
    non-zero share, which is rejected.
    """
    if count < 0:
        raise ValueError(f"offer count must be non-negative, got {count}")
    if count == 0:
        return []
    if count > total:
        raise ValueError(f"cannot give each of {count} offers a share of at least 1 of {total}")
    base, remainder = divmod(total, count)
    return [base + 1 if index < remainder else base for index in range(count)]
