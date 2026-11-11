import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strategy import TradeEvent, exit_decision, portfolio_limits

def test_migration_does_not_force_exit_or_apply_time_cap():
    position={"entry_price":1.0,"peak_price":1.0}
    result=exit_decision(position,[],1.20,now=100000,migration=True,route_verified=True)
    assert result["action"]=="HOLD"
    assert position["market"]=="PUMPSWAP"

def test_no_maximum_holding_time():
    result=exit_decision({"entry_price":1.0,"peak_price":1.0},[],1.02,now=999999)
    assert result["action"]=="HOLD"

def test_hard_stop_triggers_sell_when_route_is_available():
    result=exit_decision({"entry_price":1.0,"peak_price":1.0},[],0.94,now=10)
    assert result["action"]=="SELL"
    assert result["reason"]=="HARD_STOP"

def test_stop_trigger_waits_for_verified_route():
    result=exit_decision({"entry_price":1.0,"peak_price":1.0},[],0.94,now=10,route_verified=False)
    assert result["action"]=="HOLD_ROUTE_UNAVAILABLE"

def test_portfolio_scaling_caps_stake():
    assert portfolio_limits(8,8,1)=={"max_open_positions":1,"stake_usd":1.0}
    assert portfolio_limits(16,8,1)=={"max_open_positions":2,"stake_usd":1.5}
    assert portfolio_limits(32,8,1)=={"max_open_positions":3,"stake_usd":2.25}
