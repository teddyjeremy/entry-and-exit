"""Portfolio concurrency and one-entry-per-mint rules.

This is a pure admission policy. A future paper/live execution engine must
persist the traded-mint history and reserve an entry atomically before sending
an order; this module does not submit transactions or maintain storage.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def maximum_concurrent_positions(
    realized_portfolio_usd: float,
    milestone_usd: float = 5.0,
    starting_positions: int = 1,
) -> int:
    """One slot initially; add one slot for every full milestone of equity.

    Examples with a $5 milestone: $0-$4.99 => 1, $5-$9.99 => 2,
    $10-$14.99 => 3. Uses realized portfolio equity, not temporary
    unrealized mark-to-market gains.
    """
    if (
        isinstance(realized_portfolio_usd, bool)
        or not isinstance(realized_portfolio_usd, (int, float))
        or not math.isfinite(realized_portfolio_usd)
        or realized_portfolio_usd < 0
    ):
        raise ValueError("realized_portfolio_usd must be a finite non-negative number")
    if (
        isinstance(milestone_usd, bool)
        or not isinstance(milestone_usd, (int, float))
        or not math.isfinite(milestone_usd)
        or milestone_usd <= 0
    ):
        raise ValueError("milestone_usd must be a finite positive number")
    if isinstance(starting_positions, bool) or not isinstance(starting_positions, int) or starting_positions < 1:
        raise ValueError("starting_positions must be a positive integer")

    return starting_positions + math.floor(realized_portfolio_usd / milestone_usd)


def evaluate_entry_capacity(
    candidate_mint: str,
    realized_portfolio_usd: float,
    open_position_mints: Iterable[str],
    previously_traded_mints: Iterable[str],
    milestone_usd: float = 5.0,
    starting_positions: int = 1,
) -> dict[str, Any]:
    """Check whether a new mint may be opened under portfolio rules.

    A mint is permanently ineligible after its first entry, even after exit.
    A concurrent slot is released only when the existing position is closed.
    """
    if not isinstance(candidate_mint, str) or not candidate_mint.strip():
        return {
            "approved": False,
            "maximum_concurrent_positions": None,
            "open_positions": 0,
            "available_slots": 0,
            "rejection_reasons": ["invalid_candidate_mint"],
        }

    try:
        open_mints = list(open_position_mints)
        traded_mints = set(previously_traded_mints)
        maximum = maximum_concurrent_positions(
            realized_portfolio_usd, milestone_usd, starting_positions
        )
    except (TypeError, ValueError):
        return {
            "approved": False,
            "maximum_concurrent_positions": None,
            "open_positions": 0,
            "available_slots": 0,
            "rejection_reasons": ["invalid_portfolio_or_position_state"],
        }

    if any(not isinstance(mint, str) or not mint.strip() for mint in open_mints):
        return {
            "approved": False,
            "maximum_concurrent_positions": maximum,
            "open_positions": len(open_mints),
            "available_slots": 0,
            "rejection_reasons": ["invalid_open_position_state"],
        }
    if len(set(open_mints)) != len(open_mints):
        return {
            "approved": False,
            "maximum_concurrent_positions": maximum,
            "open_positions": len(open_mints),
            "available_slots": 0,
            "rejection_reasons": ["duplicate_open_position_state"],
        }

    reasons = []
    if candidate_mint in traded_mints or candidate_mint in open_mints:
        reasons.append("coin_already_traded")
    if len(open_mints) >= maximum:
        reasons.append("maximum_concurrent_positions_reached")

    return {
        "approved": not reasons,
        "maximum_concurrent_positions": maximum,
        "open_positions": len(open_mints),
        "available_slots": max(0, maximum - len(open_mints)),
        "rejection_reasons": reasons,
    }
