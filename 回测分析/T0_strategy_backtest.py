#!/usr/bin/env python3
"""
T+0 20条策略回测 - 日线近似模拟
评估策略能否识别出适合做T的交易日
"""
import json, os, subprocess, sys
from datetime import datetime, timedelta

CLI = "node"
CLI_SCRIPT = os.path.expanduser("~/.workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data/scripts/index.js")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

COLORS = {
    1: ("A锚点", "低吸"), 2: ("A偏离", "低吸"), 3: ("B缩跌", "低吸"),
    4: ("B放弹", "低吸"), 5: ("C多头", "低吸"), 6: ("C震荡", "双"),
    7: ("D背离", "低吸"), 8: ("D振幅", "双"), 9: ("D超卖", "低吸"),
    10: ("E开低", "低吸"), 11: ("E均支", "低吸"), 12: ("F时间", "恒真"),
    13: ("F非崩", "恒真"), 14: ("G地量", "低吸"), 15: ("G双底", "低吸"),
    16: ("H放阳", "低吸"),
}
HARD_COST = 0.0007  # 0.07% 往返成本

STOCKS = {
    "sz300750": "宁德时代", "sh688041": "海光信息", "sz300308": "中际旭创",
    "sz300502": "新易盛", "sh688025": "杰普特", "sz002222": "福晶科技",
    "sz002156": "通富微电", "sh688503": "聚和材料", "sh688062": "迈威生物",
    "sz300660": "江苏雷利", "sh688778": "厦钨新能", "sz300450": "先导智能",
    "sh601208": "东材科技", "sz300014": "亿纬锂能",
}

THRESHOLDS = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]


def run_cli(cmd):
    try:
        r = subprocess.run([CLI, CLI_SCRIPT] + cmd, capture_output=True, text=True, timeout=30,
                          encoding="utf-8", errors="replace")
        return r.stdout
    except:
        return ""


def parse_kline_csv(text):
    """解析kline命令输出的Markdown表格"""
    lines = [l.strip() for l in text.split("\n") if l.strip() and "|" in l and not l.strip().startswith("| ---")]
    data = []
    for l in lines[1:]:  # skip header
        parts = [p.strip() for p in l.split("|")[1:-1]]
        if len(parts) >= 7:
            try:
                data.append({
                    "date": parts[0], "open": float(parts[1]), "last": float(parts[2]),
                    "high": float(parts[3]), "low": float(parts[4]),
                    "volume": float(parts[5]), "amount": float(parts[6])
                })
            except: pass
    return data


def parse_tech_csv(text):
    """解析technical命令输出，提取MA和RSI"""
    lines = [l.strip() for l in text.split("\n") if l.strip() and "|" in l]
    if len(lines) < 2:
        return []
    # Find MA columns and RSI columns
    header = lines[1]
    cols = [c.strip() for c in header.split("|")[1:-1]]
    
    ma20_idx = ma60_idx = rsi6_idx = None
    for i, c in enumerate(cols):
        if "ma_20" in c.lower(): ma20_idx = i
        elif "ma_60" in c.lower(): ma60_idx = i
        elif "rsi_6" in c.lower() or "rsi.RSI_6" in c.lower(): rsi6_idx = i
    
    if ma20_idx is None and ma60_idx is None and rsi6_idx is None:
        return []
    
    data = []
    for l in lines[2:]:
        parts = [p.strip() for p in l.split("|")[1:-1]]
        if len(parts) > max(ma20_idx or 0, ma60_idx or 0, rsi6_idx or 0):
            try:
                d = {"date": parts[2] if len(parts) > 2 else ""}
                if ma20_idx is not None and parts[ma20_idx] and parts[ma20_idx] != "-":
                    d["ma20"] = float(parts[ma20_idx])
                if ma60_idx is not None and parts[ma60_idx] and parts[ma60_idx] != "-":
                    d["ma60"] = float(parts[ma60_idx])
                if rsi6_idx is not None and parts[rsi6_idx] and parts[rsi6_idx] != "-":
                    d["rsi6"] = float(parts[rsi6_idx])
                data.append(d)
            except: pass
    return data


def evaluate_day(k, prev_k, ma20, ma60, rsi6, vol_ma5, side):
    """评估某天某个方向满足多少条策略
    side: "low"=正T "high"=反T
    """
    if k is None: return 0, {}
    
    o, h, l, c, v = k["open"], k["high"], k["low"], k["last"], k["volume"]
    if o <= 0 or c <= 0 or l <= 0: return 0, {}
    
    avg_p = (h + l + c) / 3
    change_pct = (c - o) / o * 100
    range_pct = (h - l) / l * 100 if l > 0 else 0
    prev_l = prev_k["low"] if prev_k else l
    prev_v = prev_k["volume"] if prev_k else v
    v_ratio = v / vol_ma5 if vol_ma5 and vol_ma5 > 0 else 1.0
    
    met = {}
    
    # 1. A锚点: 价格接近均价
    if avg_p > 0 and abs(c - avg_p) / avg_p < 0.01:
        met["A锚点"] = f"距均价{abs(c-avg_p)/avg_p*100:.1f}%"
    
    # 2. A偏离: >2%
    if avg_p > 0 and abs(c - avg_p) / avg_p > 0.02:
        met["A偏离"] = f"偏离{abs(c-avg_p)/avg_p*100:.1f}%"
    
    # 3. B缩量下跌
    if c < o and v_ratio < 0.8:
        met["B缩跌"] = f"量比{v_ratio:.2f}"
    
    # 4. B放量反弹
    if c > o and v_ratio > 1.0:
        met["B放弹"] = f"量比{v_ratio:.2f}"
    
    # 5. C多头
    if ma20 and ma60 and ma20 > ma60 and (ma20 - ma60) / ma60 > 0.015:
        met["C多头"] = "多头排列"
    
    # 6. C震荡
    if ma20 and ma60 and abs(ma20 - ma60) / ma60 < 0.015:
        met["C震荡"] = "均线缠绕"
    
    # 7. D背离(低)
    if (c - l) / l < 0.01 and change_pct > -3:
        met["D背离"] = "价近低"
    
    # 8. D振幅
    if range_pct > 2:
        met["D振幅"] = f"振幅{range_pct:.1f}%"
    
    # 9. D超卖
    if rsi6 is not None and rsi6 < 30:
        met["D超卖"] = f"RSI{rsi6:.1f}"
    
    # 10. E开低
    if (o - l) / l < 0.01:
        met["E开低"] = "开近低点"
    
    # 11. E均支
    if ma60 and abs(c - ma60) / ma60 < 0.05:
        met["E均支"] = f"距MA60:{abs(c-ma60)/ma60*100:.1f}%"
    
    # 12. F时间（恒真）
    met["F时间"] = "OK"
    
    # 13. F非崩
    if change_pct > -5:
        met["F非崩"] = f"跌{abs(change_pct):.1f}%"
    
    # 14. G地量
    if v_ratio < 0.5 and c < o:
        met["G地量"] = f"量比{v_ratio:.2f}"
    
    # 15. G双底
    if prev_l > 0 and abs(l - prev_l) / l < 0.01 and l >= prev_l:
        met["G双底"] = "双底企稳"
    
    # 16. H放阳
    if c > o and v > vol_ma5:
        met["H放阳"] = "阳线放量"
    
    # 过滤：正T需要低吸策略，反T取相反信号
    if side == "low":
        low_sigs = {"A锚点", "A偏离", "B缩跌", "B放弹", "C多头", "C震荡",
                     "D背离", "D振幅", "D超卖", "E开低", "E均支",
                     "F时间", "F非崩", "G地量", "G双底", "H放阳"}
        met = {k: v for k, v in met.items() if k in low_sigs}
    
    return len(met), met


def get_trend(ma20, ma60):
    if not ma20 or not ma60: return "RANGE"
    diff = abs(ma20 - ma60) / ma60 * 100
    if diff < 1.5: return "RANGE"
    return "BULL" if ma20 > ma60 else "BEAR"


def backtest_stock(code, name):
    """对单个股票进行回测"""
    print(f"  回测 {name}({code})...")
    
    # Pull kline 500 days
    kline_text = run_cli(["kline", code, "--freq", "day", "--count", "300", "--fq", "qfq"])
    klines = parse_kline_csv(kline_text)
    
    # Pull tech data
    tech_text = run_cli(["technical", code, "--group", "ma,rsi", "--start", "2024-01-01", "--end", "2026-05-28"])
    techs = parse_tech_csv(tech_text)
    
    if len(klines) < 100:
        print(f"    WARN: 数据不足({len(klines)}条)，跳过")
        return None
    
    # Build tech lookup
    tech_map = {}
    for t in techs:
        d = t.get("date", "")
        if d:
            tech_map[d] = t
    
    # 按阈值分别统计
    results = {}
    for th in THRESHOLDS:
        results[th] = {"signals": 0, "wins": 0, "returns": [], 
                        "strat_counts": {}, "trades": []}
    
    # 滑动计算vol_ma5
    vol_ma5_list = []
    for i, k in enumerate(klines):
        if i >= 4:
            avg5 = sum(klines[j]["volume"] for j in range(i-4, i+1)) / 5
        else:
            avg5 = k["volume"] if k["volume"] > 0 else 1
        vol_ma5_list.append(avg5)
    
    # 逐日评估
    signal_cooldown = 0
    for i, k in enumerate(klines):
        if signal_cooldown > 0:
            signal_cooldown -= 1
            continue
        
        d = k["date"]
        prev_k = klines[i-1] if i > 0 else None
        vol_ma5 = vol_ma5_list[i] if i < len(vol_ma5_list) else (k["volume"] or 1)
        
        tinfo = tech_map.get(d, {})
        ma20 = tinfo.get("ma20")
        ma60 = tinfo.get("ma60")
        rsi6 = tinfo.get("rsi6")
        
        trend = get_trend(ma20, ma60)
        
        # 决定方向
        if trend == "BULL":
            side = "low"  # 正T
        elif trend == "BEAR":
            side = "high"  # 反T
        else:
            side = "low"  # 震荡偏向正T
        
        count, met_strategies = evaluate_day(k, prev_k, ma20, ma60, rsi6, vol_ma5, side)
        
        total_enabled = 16  # 假设全部启用
        
        # 对每个阈值检查
        for th in THRESHOLDS:
            required = max(1, int(total_enabled * th))
            if count >= required:
                results[th]["signals"] += 1
                
                # 计算T+0收益
                if side == "low":
                    # 正T：开买→收卖
                    ret = k["last"] / k["open"] - 1 - HARD_COST
                else:
                    # 反T：开卖→收买
                    ret = 1 - k["last"] / k["open"] - HARD_COST
                
                results[th]["returns"].append(ret)
                if ret > 0:
                    results[th]["wins"] += 1
                
                results[th]["trades"].append({
                    "date": d, "side": side, "trend": trend,
                    "count": count, "ret": round(ret, 4),
                    "strategies": list(met_strategies.keys()),
                })
                
                # 统计策略出现频次
                for s in met_strategies:
                    results[th]["strat_counts"][s] = results[th]["strat_counts"].get(s, 0) + 1
                
                signal_cooldown = 3  # 冷却3天
                break  # 只记录一次
    
    # 计算汇总统计
    summary = {}
    for th in THRESHOLDS:
        r = results[th]
        n = r["signals"]
        if n > 0:
            avg_ret = sum(r["returns"]) / n
            win_rate = r["wins"] / n
            pos_returns = [x for x in r["returns"] if x > 0]
            neg_returns = [x for x in r["returns"] if x <= 0]
            avg_win = sum(pos_returns) / len(pos_returns) if pos_returns else 0
            avg_loss = sum(neg_returns) / len(neg_returns) if neg_returns else 0
            summary[th] = {
                "signals": n, "winRate": round(win_rate, 3),
                "avgReturn": round(avg_ret, 4), "avgWin": round(avg_win, 4),
                "avgLoss": round(avg_loss, 4), "totalReturn": round(sum(r["returns"]), 4),
            }
        else:
            summary[th] = {"signals": 0}
    
    return {"code": code, "name": name, "summary": summary, 
            "strat_counts": results[min(THRESHOLDS)]["strat_counts"]}


def main():
    print("=" * 60)
    print("T+0 20条策略回测 | 近2年日线近似")
    print("=" * 60)
    
    all_results = {}
    all_strat_counts = {}
    
    for code, name in STOCKS.items():
        try:
            r = backtest_stock(code, name)
            if r:
                all_results[code] = r
                for s, cnt in r.get("strat_counts", {}).items():
                    all_strat_counts[s] = all_strat_counts.get(s, 0) + cnt
        except Exception as e:
            print(f"    ❌ {name} 回测失败: {e}")
    
    # 汇总统计
    print("\nSummary Results")
    print("=" * 60)
    
    for th in THRESHOLDS:
        signals = 0; wins = 0; returns = []
        for r in all_results.values():
            s = r["summary"].get(th, {})
            signals += s.get("signals", 0)
            if s.get("signals", 0) > 0:
                n = s["signals"]
                wins += int(n * s.get("winRate", 0))
                # 从avgReturn反推总return
                returns.extend([s.get("avgReturn", 0)] * n)
        
        if signals > 0:
            wr = wins / signals
            ar = sum(returns) / len(returns) if returns else 0
            tr = sum(returns)
            print(f"\n  阈值 {int(th*100)}%: 信号{signals}次 | 胜率{wr*100:.1f}% | 均笔{ar*100:.2f}% | 累计{tr*100:.2f}%")
        else:
            print(f"\n  阈值 {int(th*100)}%: 无信号")
    
    # 策略贡献排行
    print(f"\nStrategy Frequency (threshold 15%):")
    sorted_strats = sorted(all_strat_counts.items(), key=lambda x: -x[1])
    for s, cnt in sorted_strats[:10]:
        bar = "▓" * min(cnt // 5, 30)
        print(f"  {s}: {cnt}次 {bar}")
    
    # 保存结果
    os.makedirs(DATA_DIR, exist_ok=True)
    result_file = os.path.join(DATA_DIR, "backtest-summary.json")
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "results": all_results,
            "strat_counts": all_strat_counts,
            "thresholds": [int(t*100) for t in THRESHOLDS],
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 结果已保存: {result_file}")

if __name__ == "__main__":
    main()
