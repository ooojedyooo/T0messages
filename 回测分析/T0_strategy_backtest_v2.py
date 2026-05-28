#!/usr/bin/env python3
"""
T+0 策略回测 v2 - 深层分析
- 去掉恒真策略(F时间/D振幅/F非崩)
- 无冷却期
- 按趋势/波动率分组统计
- 盘前过滤有效性测试
"""
import json, os, subprocess, sys
from datetime import datetime

CLI = "node"
CLI_SCRIPT = os.path.expanduser("~/.workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data/scripts/index.js")

_BT_ROOT = os.path.dirname(os.path.abspath(__file__))
_BT_DATE = datetime.now().strftime("%Y-%m-%d")
DATA_DIR = os.path.join(_BT_ROOT, f"{_BT_DATE}-回测", "data")
os.makedirs(DATA_DIR, exist_ok=True)

HARD_COST = 0.0007

STOCKS = {
    "sz300750": "宁德时代", "sh688041": "海光信息", "sz300308": "中际旭创",
    "sz300502": "新易盛", "sh688025": "杰普特", "sz002222": "福晶科技",
    "sz002156": "通富微电", "sh688503": "聚和材料", "sh688062": "迈威生物",
    "sz300660": "江苏雷利", "sh688778": "厦钨新能", "sz300450": "先导智能",
    "sh601208": "东材科技", "sz300014": "亿纬锂能",
}

# 只保留13条有区分度的策略（去掉F时间/F非崩/D振幅）
REAL_STRATEGIES = [
    "A锚点", "A偏离", "B缩跌", "B放弹", "C多头", "C震荡",
    "D背离", "E开低", "E均支", "G地量", "G双底", "H放阳",
]
N_REAL = len(REAL_STRATEGIES)

def run_cli(cmd):
    try:
        r = subprocess.run([CLI, CLI_SCRIPT] + cmd, capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace")
        return r.stdout
    except: return ""

def parse_kline_csv(text):
    lines = [l.strip() for l in text.split("\n") if l.strip() and "|" in l and not l.strip().startswith("| ---")]
    data = []
    for l in lines[1:]:
        parts = [p.strip() for p in l.split("|")[1:-1]]
        if len(parts) >= 7:
            try:
                data.append({"date": parts[0], "open": float(parts[1]), "last": float(parts[2]),
                            "high": float(parts[3]), "low": float(parts[4]),
                            "volume": float(parts[5]), "amount": float(parts[6])})
            except: pass
    return data

def parse_tech_csv(text):
    lines = [l.strip() for l in text.split("\n") if l.strip() and "|" in l]
    if len(lines) < 2: return []
    header = lines[1]
    cols = [c.strip() for c in header.split("|")[1:-1]]
    ma20_idx = ma60_idx = rsi6_idx = None
    for i, c in enumerate(cols):
        if "ma_20" in c.lower(): ma20_idx = i
        elif "ma_60" in c.lower(): ma60_idx = i
        elif "rsi_6" in c.lower() or "rsi.RSI_6" in c.lower(): rsi6_idx = i
    if ma20_idx is None and ma60_idx is None and rsi6_idx is None: return []
    data = []
    for l in lines[2:]:
        parts = [p.strip() for p in l.split("|")[1:-1]]
        if len(parts) > max(ma20_idx or 0, ma60_idx or 0, rsi6_idx or 0):
            try:
                d = {"date": parts[2] if len(parts) > 2 else ""}
                if ma20_idx is not None and parts[ma20_idx] and parts[ma20_idx] != "-": d["ma20"] = float(parts[ma20_idx])
                if ma60_idx is not None and parts[ma60_idx] and parts[ma60_idx] != "-": d["ma60"] = float(parts[ma60_idx])
                if rsi6_idx is not None and parts[rsi6_idx] and parts[rsi6_idx] != "-": d["rsi6"] = float(parts[rsi6_idx])
                data.append(d)
            except: pass
    return data

def evaluate_day_v2(k, prev_k, ma20, ma60, rsi6, vol_ma5, side):
    if k is None: return 0, []
    o, h, l, c, v = k["open"], k["high"], k["low"], k["last"], k["volume"]
    if o <= 0 or c <= 0 or l <= 0: return 0, []
    
    avg_p = (h + l + c) / 3
    change_pct = (c - o) / o * 100
    prev_l = prev_k["low"] if prev_k else l
    v_ratio = v / vol_ma5 if vol_ma5 and vol_ma5 > 0 else 1.0
    amplitude = (h - l) / l * 100 if l > 0 else 0
    
    met = []
    
    # A锚点
    if avg_p > 0 and abs(c - avg_p) / avg_p < 0.01:
        met.append("A锚点")
    # A偏离
    if avg_p > 0 and abs(c - avg_p) / avg_p > 0.02:
        met.append("A偏离")
    # B缩跌
    if c < o and v_ratio < 0.8:
        met.append("B缩跌")
    # B放弹
    if c > o and v_ratio > 1.0:
        met.append("B放弹")
    # C多头
    if ma20 and ma60 and ma20 > ma60 and (ma20 - ma60) / ma60 > 0.015:
        met.append("C多头")
    # C震荡
    if ma20 and ma60 and abs(ma20 - ma60) / ma60 < 0.015:
        met.append("C震荡")
    # D背离
    if (c - l) / l < 0.01 and change_pct > -3:
        met.append("D背离")
    # E开低
    if (o - l) / l < 0.01:
        met.append("E开低")
    # E均支
    if ma60 and abs(c - ma60) / ma60 < 0.05:
        met.append("E均支")
    # G地量
    if v_ratio < 0.5 and c < o:
        met.append("G地量")
    # G双底
    if prev_l > 0 and abs(l - prev_l) / l < 0.01 and l >= prev_l:
        met.append("G双底")
    # H放阳
    if c > o and v > vol_ma5:
        met.append("H放阳")
    
    return len(met), met

def get_trend(ma20, ma60):
    if not ma20 or not ma60: return "RANGE"
    diff = abs(ma20 - ma60) / ma60 * 100
    if diff < 1.5: return "RANGE"
    return "BULL" if ma20 > ma60 else "BEAR"

def backtest_stock_v2(code, name):
    kline_text = run_cli(["kline", code, "--freq", "day", "--count", "300", "--fq", "qfq"])
    klines = parse_kline_csv(kline_text)
    tech_text = run_cli(["technical", code, "--group", "ma,rsi", "--start", "2024-01-01", "--end", "2026-05-28"])
    techs = parse_tech_csv(tech_text)
    if len(klines) < 100: return None
    
    tech_map = {}
    for t in techs:
        d = t.get("date", "")
        if d: tech_map[d] = t
    
    # Compute rolling stats
    vol_ma5_list = []
    ampl_ma20_list = []  # 20-day average amplitude
    for i, k in enumerate(klines):
        if i >= 4:
            avg5 = sum(klines[j]["volume"] for j in range(i-4, i+1)) / 5
        else:
            avg5 = k["volume"] if k["volume"] > 0 else 1
        vol_ma5_list.append(avg5)
        
        if i >= 19:
            avg_amp = sum((klines[j]["high"]-klines[j]["low"])/klines[j]["low"]*100 for j in range(i-19, i+1)) / 20
        else:
            avg_amp = 0
        ampl_ma20_list.append(avg_amp)
    
    # Collect ALL trades (no cooldown)
    all_trades = []
    
    for i, k in enumerate(klines):
        d = k["date"]
        prev_k = klines[i-1] if i > 0 else None
        vol_ma5 = vol_ma5_list[i]
        ampl_20 = ampl_ma20_list[i]
        
        tinfo = tech_map.get(d, {})
        ma20 = tinfo.get("ma20"); ma60 = tinfo.get("ma60"); rsi6 = tinfo.get("rsi6")
        
        trend = get_trend(ma20, ma60)
        side = "low" if trend != "BEAR" else "high"
        
        count, strategies = evaluate_day_v2(k, prev_k, ma20, ma60, rsi6, vol_ma5, side)
        
        # 分层统计
        amplitude = (k["high"]-k["low"])/k["low"]*100 if k["low"]>0 else 0
        change_day = (k["last"]-k["open"])/k["open"]*100
        
        for th_pct in [0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]:
            required = max(1, int(N_REAL * th_pct))
            if count >= required:
                if side == "low":
                    ret = k["last"] / k["open"] - 1 - HARD_COST
                else:
                    ret = 1 - k["last"] / k["open"] - HARD_COST
                
                all_trades.append({
                    "date": d, "side": side, "trend": trend, "count": count,
                    "ret": round(ret, 4), "strategies": strategies,
                    "amplitude": round(amplitude, 2), "ampl_20d": round(ampl_20, 2),
                    "change": round(change_day, 2), "rsi6": rsi6,
                })
                break  # one entry per day
    
    return {"code": code, "name": name, "trades": all_trades}

def analyze(results):
    print("=" * 70)
    print("T+0 Strategy Backtest v2 - Deep Analysis")
    print("=" * 70)
    print(f"Real strategies: {N_REAL} (removed F-time/F-not-crash/D-amplitude)")
    print(f"Stocks: {len(results)}")
    print()
    
    # ---- Threshold Analysis ----
    print("=== 1. Threshold Scan (all stocks) ===")
    print(f"{'Thr':>6} {'Signals':>8} {'WR':>7} {'AvgR':>8} {'CumR':>8}")
    print("-" * 45)
    for th_pct in [0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]:
        all_t = []
        for r in results:
            for t in r["trades"]:
                all_t.append(t)
        
        # Filter by threshold (trades already filtered per-threshold during collection)
        # Actually we need to re-filter, all_t has mixed thresholds
        # Let's simplify - just count by the 'count' field
        required = max(1, int(N_REAL * th_pct))
        filtered = [t for t in all_t if t["count"] >= required]
        n = len(filtered)
        if n > 0:
            wr = sum(1 for t in filtered if t["ret"]>0)/n
            ar = sum(t["ret"] for t in filtered)/n
            cr = sum(t["ret"] for t in filtered)
            print(f" {int(th_pct*100):>4}% {n:>8} {wr*100:>6.1f}% {ar*100:>+7.2f}% {cr*100:>+7.2f}%")
        else:
            print(f" {int(th_pct*100):>4}% {0:>8}    -       -       -")
    
    print()
    
    # ---- Trend Analysis ----
    print("=== 2. Performance by Trend ===")
    for trend in ["BULL", "BEAR", "RANGE"]:
        filtered = []
        for r in results:
            for t in r["trades"]:
                if t["trend"] == trend and t["count"] >= 2:  # ~15% of 13
                    filtered.append(t)
        n = len(filtered)
        if n > 0:
            wr = sum(1 for t in filtered if t["ret"]>0)/n
            ar = sum(t["ret"] for t in filtered)/n
            print(f"  {trend:<6}: {n:>5} trades, WR={wr*100:.1f}%, AvgR={ar*100:+.2f}%")
        else:
            print(f"  {trend:<6}: No trades")
    
    print()
    
    # ---- Volatility Analysis ----
    print("=== 3. Performance by Amplitude Bracket ===")
    brackets = [(0, 2, "Low(<2%)"), (2, 3, "Mid(2-3%)"), (3, 5, "High(3-5%)"), (5, 20, "Extreme(>5%)")]
    for lo, hi, label in brackets:
        filtered = []
        for r in results:
            for t in r["trades"]:
                if lo <= t["amplitude"] < hi and t["count"] >= 2:
                    filtered.append(t)
        n = len(filtered)
        if n > 0:
            wr = sum(1 for t in filtered if t["ret"]>0)/n
            ar = sum(t["ret"] for t in filtered)/n
            print(f"  {label:<15}: {n:>5} trades, WR={wr*100:.1f}%, AvgR={ar*100:+.2f}%")
    
    print()
    
    # ---- Pre-market Filter Analysis ----
    print("=== 4. Pre-Market Filter Effectiveness ===")
    filters = {
        "All (no filter)": lambda t: True,
        "Ampl 20d > 3%": lambda t: t.get("ampl_20d", 0) > 3,
        "Ampl 20d > 4%": lambda t: t.get("ampl_20d", 0) > 4,
        "Not BEAR trend": lambda t: t["trend"] != "BEAR",
        "BULL only": lambda t: t["trend"] == "BULL",
        "Amp>2% + BULL": lambda t: t.get("amplitude", 0) > 2 and t["trend"] == "BULL",
    }
    for name, fn in filters.items():
        filtered = []
        for r in results:
            for t in r["trades"]:
                if fn(t) and t["count"] >= 2:
                    filtered.append(t)
        n = len(filtered)
        if n > 0:
            wr = sum(1 for t in filtered if t["ret"]>0)/n
            ar = sum(t["ret"] for t in filtered)/n
            print(f"  {name:<20}: {n:>4} trades, WR={wr*100:.1f}%, AvgR={ar*100:+.2f}%")
        else:
            print(f"  {name:<20}: No trades")
    
    print()
    
    # ---- Stock Ranking ----
    print("=== 5. Stock Ranking (15% threshold equivalent, ~2/13) ===")
    req = max(1, int(N_REAL * 0.15))
    for r in sorted(results, key=lambda x: -sum(t["ret"] for t in x["trades"] if t["count"]>=req)):
        trades = [t for t in r["trades"] if t["count"] >= req]
        n = len(trades)
        if n > 0:
            wr = sum(1 for t in trades if t["ret"]>0)/n
            ar = sum(t["ret"] for t in trades)/n
            cr = sum(t["ret"] for t in trades)
            print(f"  {r['name']:<10}: {n:>4} trades, WR={wr*100:.0f}%, CumR={cr*100:+.1f}%, AvgR={ar*100:+.2f}%")
    
    # Save
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "backtest-v2.json"), "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, ensure_ascii=False, indent=2, default=str)

def main():
    results = {}
    for code, name in STOCKS.items():
        try:
            r = backtest_stock_v2(code, name)
            if r: results[code] = r
        except Exception as e:
            print(f"  FAIL {name}: {e}")
    analyze(list(results.values()))

if __name__ == "__main__":
    main()
