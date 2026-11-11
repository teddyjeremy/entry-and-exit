import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strategy import exit_decision, portfolio_limits

class PaperStrategyTests(unittest.TestCase):
    def test_migration_does_not_force_exit(self):
        position={"entry_price":1.0,"peak_price":1.0}
        result=exit_decision(position,[],1.20,now=100000,migration=True,route_verified=True)
        self.assertEqual(result["action"],"HOLD")
        self.assertEqual(position["market"],"PUMPSWAP")
    def test_no_maximum_holding_time(self):
        result=exit_decision({"entry_price":1.0,"peak_price":1.0},[],1.02,now=999999)
        self.assertEqual(result["action"],"HOLD")
    def test_hard_stop_sells_when_route_is_verified(self):
        result=exit_decision({"entry_price":1.0,"peak_price":1.0},[],0.94,now=10)
        self.assertEqual(result["action"],"SELL")
        self.assertEqual(result["reason"],"HARD_STOP")
    def test_stop_waits_if_route_is_unavailable(self):
        result=exit_decision({"entry_price":1.0,"peak_price":1.0},[],0.94,now=10,route_verified=False)
        self.assertEqual(result["action"],"HOLD_ROUTE_UNAVAILABLE")
    def test_portfolio_scaling(self):
        self.assertEqual(portfolio_limits(8,8,1),{"max_open_positions":1,"stake_usd":1.0})
        self.assertEqual(portfolio_limits(16,8,1),{"max_open_positions":2,"stake_usd":1.5})
        self.assertEqual(portfolio_limits(32,8,1),{"max_open_positions":3,"stake_usd":2.25})

if __name__=="__main__": unittest.main()
