"""Fail-closed preflight eligibility checks for the paper strategy baseline."""

from __future__ import annotations

import math
from typing import Any


def _number(snapshot: dict[str, Any], key: str, reasons: list[str]) -> float | None:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        reasons.append(f"missing_or_invalid:{key}")
        return None
    return float(value)


def evaluate_eligibility(snapshot: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Return an approval decision and stable rejection codes.

    This is a fail-closed preflight gate, not a transaction parser or trading engine.
    The caller must derive every field from verified, point-in-time chain evidence.
    """
    if not isinstance(snapshot, dict):
        return {"approved": False, "rejection_reasons": ["invalid_snapshot"]}

    reasons: list[str] = []
    boolean_requirements = {
        "is_pump_fun_bonding_curve": True,
        "bonding_curve_active": True,
        "migrated": False,
        "market_state_known": True,
        "buy_quote_available": True,
        "sell_quote_available": True,
    }
    for key, expected in boolean_requirements.items():
        actual = snapshot.get(key)
        if not isinstance(actual, bool):
            reasons.append(f"missing_or_invalid:{key}")
        elif actual is not expected:
            reasons.append(f"failed:{key}")

    market = config.get("market_filters", {})
    execution = config.get("execution_guards", {})
    freshness = config.get("freshness", {})
    numeric_checks = [
        ("market_cap_usd", "minimum_market_cap_usd", "min"),
        ("real_bonding_curve_sol_reserves", "minimum_real_bonding_curve_sol_reserves", "min"),
        ("volume_sol_30s", "minimum_volume_sol_rolling_30_seconds", "min"),
        ("unique_buyers_30s", "minimum_unique_buyers_rolling_30_seconds", "min"),
        ("entry_price_impact_percent", "maximum_entry_price_impact_percent", "max"),
        ("exit_price_impact_percent", "maximum_exit_price_impact_percent", "max"),
        ("round_trip_cost_percent", "maximum_round_trip_cost_percent", "max"),
        ("rpc_data_age_seconds", "maximum_rpc_data_age_seconds", "max"),
        ("signal_age_seconds", "maximum_signal_age_seconds", "max"),
        ("buy_quote_age_seconds", "maximum_quote_age_seconds", "max"),
        ("sell_quote_age_seconds", "maximum_quote_age_seconds", "max"),
    ]
    for snapshot_key, config_key, direction in numeric_checks:
        section = freshness if config_key.startswith("maximum_") and config_key in freshness else (execution if config_key.startswith("maximum_") and config_key in execution else market)
        value = _number(snapshot, snapshot_key, reasons)
        threshold = section.get(config_key)
        if value is None:
            continue
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            reasons.append(f"invalid_config:{config_key}")
            continue
        if value < 0:
            reasons.append(f"negative_value:{snapshot_key}")
        elif direction == "min" and value < threshold:
            reasons.append(f"below_minimum:{snapshot_key}")
        elif direction == "max" and value > threshold:
            reasons.append(f"above_maximum:{snapshot_key}")

    return {"approved": not reasons, "rejection_reasons": reasons}
