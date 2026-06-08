from typing import Literal

from core.models import Greeks


def filter_strikes(
    strikes: list[float],
    underlying_price: float,
    max_distance: int = 10,
) -> list[float]:
    if not strikes:
        return []
    sorted_strikes = sorted(strikes)
    atm_idx = min(
        range(len(sorted_strikes)),
        key=lambda i: (abs(sorted_strikes[i] - underlying_price), sorted_strikes[i]),
    )
    lo = max(0, atm_idx - max_distance)
    hi = min(len(sorted_strikes), atm_idx + max_distance + 1)
    return sorted_strikes[lo:hi]


def select_atm(
    strikes: list[float],
    underlying_price: float,
    offset: int = 0,
) -> float:
    if not strikes:
        raise ValueError("no strikes available")
    sorted_strikes = sorted(strikes)
    atm_idx = min(
        range(len(sorted_strikes)),
        key=lambda i: (abs(sorted_strikes[i] - underlying_price), sorted_strikes[i]),
    )
    target_idx = atm_idx + offset
    if target_idx < 0 or target_idx >= len(sorted_strikes):
        raise ValueError(
            f"offset {offset} out of range, only {len(sorted_strikes)} strikes available"
        )
    return sorted_strikes[target_idx]


def select_by_delta(
    strikes: list[float],
    greeks_map: dict[float, Greeks],
    target_delta: float,
    right: Literal["C", "P"],
) -> float:
    candidates: list[tuple[float, float]] = []
    for strike in strikes:
        g = greeks_map.get(strike)
        if g is None:
            continue
        delta_val = abs(g.delta) if right == "P" else g.delta
        distance = round(abs(delta_val - target_delta), 6)
        candidates.append((strike, distance))
    if not candidates:
        raise ValueError("no greeks available for any strike")
    candidates.sort(key=lambda c: (c[1], c[0]))
    return candidates[0][0]


def select_strike(
    strikes: list[float],
    underlying_price: float,
    right: Literal["C", "P"],
    target_delta: float | None = None,
    greeks_map: dict[float, Greeks] | None = None,
    offset: int = 0,
) -> float:
    if target_delta is not None and greeks_map is not None:
        return select_by_delta(strikes, greeks_map, target_delta, right)
    return select_atm(strikes, underlying_price, offset)
