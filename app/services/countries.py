"""ISO 3166-1 alpha-2 country codes."""

from functools import cache

import pycountry


@cache
def countries() -> dict[str, str]:
    """Code -> name, sorted by code."""
    return {c.alpha_2: c.name for c in sorted(pycountry.countries, key=lambda c: c.alpha_2)}


def is_country_code(code: str) -> bool:
    return code in countries()
