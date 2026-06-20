// Live dashboard feed for demo-boro.html (window.DASH).
// Regenerate with real data:  python -m scripts.export_dashboard --capital 50000
// The block below is SAMPLE data (sample:true) so the UI renders before a live
// scan produces signals — export_dashboard.py overwrites it (and drops the flag).
window.DASH = {
  "sample": true,
  "asof": "2026-06-20T16:58:25",
  "signals": {
    "cards": [
      { "ticker": "RELIANCE", "signal": "BUY", "score": 86, "price": 2945, "entry": 2945,
        "stop": 2850, "target": 3182, "rr": 2.5, "shares": 3, "invest": 8835,
        "risk_rs": 285, "reward_rs": 711, "rsi": 58.4, "vol_surge": 1.42, "ret_5d": 3.1,
        "stop_trigger": 2864.25, "target_trigger": 3166.09, "cap_pct": 17.7,
        "criteria": { "rsi_healthy": true, "macd_bullish": true, "above_sma20": true,
          "above_sma50": true, "volume_surge": true, "bb_position": true, "momentum": true } },
      { "ticker": "TCS", "signal": "BUY", "score": 79, "price": 4120, "entry": 4120,
        "stop": 3995, "target": 4432, "rr": 2.5, "shares": 2, "invest": 8240,
        "risk_rs": 250, "reward_rs": 624, "rsi": 61.2, "vol_surge": 1.28, "ret_5d": 2.4,
        "stop_trigger": 4014.98, "target_trigger": 4409.84, "cap_pct": 16.5,
        "criteria": { "rsi_healthy": true, "macd_bullish": true, "above_sma20": true,
          "above_sma50": true, "volume_surge": true, "bb_position": false, "momentum": true } },
      { "ticker": "HINDUNILVR", "signal": "BUY", "score": 72, "price": 2380, "entry": 2380,
        "stop": 2305, "target": 2567, "rr": 2.49, "shares": 4, "invest": 9520,
        "risk_rs": 300, "reward_rs": 748, "rsi": 54.0, "vol_surge": 1.21, "ret_5d": 1.2,
        "stop_trigger": 2316.53, "target_trigger": 2554.17, "cap_pct": 19.0,
        "criteria": { "rsi_healthy": true, "macd_bullish": true, "above_sma20": true,
          "above_sma50": false, "volume_surge": true, "bb_position": true, "momentum": true } }
    ],
    "blocked": ["INFY", "ASIANPAINT"],
    "near_misses": [
      { "ticker": "WIPRO", "signal": "BUY", "score": 64, "price": 545, "entry": 545,
        "stop": 528, "target": 587, "rr": 2.47, "shares": 18, "invest": 9810,
        "risk_rs": 306, "reward_rs": 756, "rsi": 49.5, "vol_surge": 1.05, "ret_5d": 0.6,
        "stop_trigger": 530.64, "target_trigger": 584.07, "cap_pct": 19.6,
        "criteria": { "rsi_healthy": true, "macd_bullish": false, "above_sma20": true,
          "above_sma50": true, "volume_surge": false, "bb_position": true, "momentum": true } }
    ],
    "regime": {
      "name": "RANGING", "confidence": 56.1, "vix": 12.97, "nifty_price": 24013.1,
      "nifty_ret1w": 1.65, "nifty_ret1m": 1.5, "adv_decline": 0.0,
      "description": "Sideways market. Mean-reversion setups only.",
      "max_positions": 2, "position_size_mul": 0.7, "min_score": 72, "use_trailing_stop": false
    },
    "sectors": ["Infra", "Auto"],
    "capital": 50000.0
  },
  "portfolio": {
    "cash": 28150.0, "positions_val": 23090.0, "total_val": 51240.0,
    "total_pnl": 1240.0, "total_pnl_pct": 2.48,
    "marked": {
      "RELIANCE": { "shares": 3, "avg_entry": 2880, "stop": 2790, "target": 3120,
        "current_price": 2945, "market_value": 8835, "unrealised": 195, "unrealised_pct": 2.26 },
      "TCS": { "shares": 2, "avg_entry": 4040, "stop": 3920, "target": 4350,
        "current_price": 4120, "market_value": 8240, "unrealised": 160, "unrealised_pct": 1.98 },
      "HDFCBANK": { "shares": 3, "avg_entry": 1985, "stop": 1920, "target": 2150,
        "current_price": 2005, "market_value": 6015, "unrealised": 60, "unrealised_pct": 1.01 }
    },
    "stats": { "total_trades": 14, "wins": 9, "losses": 5, "win_rate": 64.3, "avg_win": 612, "avg_loss": -284 },
    "trades": [
      { "ticker": "MARUTI", "shares": 1, "entry": 11200, "exit": 11820, "pnl": 620, "reason": "target", "closed_at": "2026-06-12" },
      { "ticker": "ITC", "shares": 20, "entry": 432, "exit": 419, "pnl": -260, "reason": "stop", "closed_at": "2026-06-15" },
      { "ticker": "INFY", "shares": 6, "entry": 1540, "exit": 1638, "pnl": 588, "reason": "target", "closed_at": "2026-06-18" }
    ]
  },
  "equity": {
    "ticker": "RELIANCE", "asof": "2026-06-19T22:10:00", "source": "results/2026-06-19/RELIANCE_trade_log.csv",
    "curve": [50000, 50420, 50180, 51020, 51640, 51310, 52280, 53090, 52740, 53910,
              54620, 54180, 55340, 56210, 55870, 57020, 58140, 57690, 58930, 60110,
              59640, 60880, 62050, 61590, 62870, 64020, 63540, 64910, 66180, 65720]
  }
};
