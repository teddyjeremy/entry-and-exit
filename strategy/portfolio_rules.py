"""Portfolio concurrency, one-entry-per-mint, and stake-sizing rules.

These are pure policies. A future paper/live execution engine must persist
trade history and reserve entries atomically; this module does not execute orders.
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


def trade_stake_usd(
    realized_portfolio_usd: float,
    starting_portfolio_usd: float = 2.70,
    starting_stake_usd: float = 1.00,
    growth_per_doubling: float = 1.50,
    maximum_stake_usd: float = 100.00,
) -> float:
    """Size each trade at +50% for each doubling of realized portfolio equity.

    The first tier is anchored to the configured starting portfolio. Equity
    below that baseline does not earn a larger tier; stake is also capped at
    available equity and at the configured $100 maximum.
    """
    values = {
        "realized_portfolio_usd": realized_portfolio_usd,
        "starting_portfolio_usd": starting_portfolio_usd,
        "starting_stake_usd": starting_stake_usd,
        "growth_per_doubling": growth_per_doubling,
        "maximum_stake_usd": maximum_stake_usd,
    }
    for name, value in values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{name} must be a finite number")

    if realized_portfolio_usd < 0:
        raise ValueError("realized_portfolio_usd must be non-negative")
    if starting_portfolio_usd <= 0 or starting_stake_usd <= 0:
        raise ValueError("starting portfolio and starting stake must be positive")
    if growth_per_doubling < 1:
        raise ValueError("growth_per_doubling must be at least 1")
    if maximum_stake_usd <= 0:
        raise ValueError("maximum_stake_usd must be positive")
    if realized_portfolio_usd == 0:
        return 0.0

    doublings = 0
    if realized_portfolio_usd >= starting_portfolio_usd:
        ratio = realized_portfolio_usd / starting_portfolio_usd
        # Small epsilon avoids floating-point errors at exact doubling tiers.
        doublings = math.floor(math.log2(ratio) + 1e-12)

    calculated = starting_stake_usd * (growth_per_doubling ** doublings)
    return round(min(calculated, maximum_stake_usd, realized_portfolio_usd), 2)


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
