#!/usr/bin/env python3
"""
T+0 仪表盘静态页面生成器 v2.0
功能：生成一个纯静态 HTML，通过 JS fetch() 动态读取 ../data/*.json
用法：python generate_dashboard.py
      或在 t0_monitor 每次检查后自动调用

HTML 只生成一次结构骨架，数据由 JS 动态拉取 JSON 文件，
30秒自动刷新数据，无需重新生成 HTML。
"""

import json
import os
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_SCRIPT_DIR, "data")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
OUTPUT_HTML = os.path.join(DATA_DIR, "dashboard.html")

STOCK_NAMES = {
    "sz002594": "比亚迪", "sz300750": "宁德时代", "sh688041": "海光信息",
    "sz300308": "中际旭创", "sz300502": "新易盛", "sh688025": "杰普特",
    "sz002222": "福晶科技", "sz002156": "通富微电", "sh688503": "聚和材料",
    "sh688062": "迈威生物", "sz300660": "江苏雷利", "sh688778": "厦钨新能",
    "sz300450": "先导智能", "sh601208": "东材科技", "sz300014": "亿纬锂能"
}
ALL_CODES = list(STOCK_NAMES.keys())
T0_DISABLED = {"sz002594"}  # 比亚迪仅监控


def generate_html():
    os.makedirs(REPORTS_DIR, exist_ok=True)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>T+0 盯盘仪表盘 v2.0</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-dim: #8b949e; --text-bright: #f0f6fc;
    --green: #3fb950; --red: #f85149; --blue: #58a6ff;
    --yellow: #d29922; --purple: #bc8cff;
  }}
  body {{ font-family: -apple-system, 'Microsoft YaHei', 'PingFang SC', sans-serif; background: var(--bg); color: var(--text); padding: 16px; max-width: 1400px; margin: 0 auto; }}
  .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 12px; }}
  .header h1 {{ font-size: 22px; color: var(--blue); }}
  .header-right {{ display: flex; align-items: center; gap: 12px; }}
  .refresh-btn {{ background: var(--blue); color: #000; border: none; padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: bold; }}
  .refresh-btn:hover {{ opacity: 0.8; }}
  .refresh-info {{ font-size: 12px; color: var(--text-dim); }}
  .refresh-info.error {{ color: var(--red); }}
  .strategy-bar {{ display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; font-size: 13px; }}
  .strategy-tag {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; }}
  .strategy-tag .label {{ color: var(--text-dim); margin-right: 6px; }}
  .strategy-tag .value {{ color: var(--text-bright); font-weight: bold; }}
  .status-bar {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 20px; }}
  .status-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; display: flex; align-items: center; gap: 12px; }}
  .status-card .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .dot.green {{ background: var(--green); box-shadow: 0 0 8px var(--green); }}
  .dot.red {{ background: var(--red); box-shadow: 0 0 8px var(--red); }}
  .dot.yellow {{ background: var(--yellow); }}
  .dot.blue {{ background: var(--blue); }}
  .dot.purple {{ background: var(--purple); }}
  .dot.gray {{ background: #484f58; }}
  .pulse {{ animation: pulse 2s infinite; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
  .status-card .label {{ font-size: 12px; color: var(--text-dim); }}
  .status-card .value {{ font-size: 16px; font-weight: bold; color: var(--text-bright); }}
  .section-title {{ color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  .stock-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 10px; }}
  .stock-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; transition: border-color 0.2s; }}
  .stock-card:hover {{ border-color: var(--blue); }}
  .stock-card.disabled {{ opacity: 0.5; }}
  .stock-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .stock-name {{ font-size: 15px; font-weight: bold; color: var(--text-bright); }}
  .stock-code {{ font-size: 11px; color: var(--text-dim); }}
  .stock-price {{ font-size: 20px; font-weight: bold; }}
  .stock-change {{ font-size: 13px; font-weight: bold; padding: 2px 6px; border-radius: 4px; }}
  .stock-change.up {{ color: var(--red); background: rgba(248,81,73,0.1); }}
  .stock-change.down {{ color: var(--green); background: rgba(63,185,80,0.1); }}
  .stock-meta {{ font-size: 11px; color: var(--text-dim); margin-top: 2px; }}
  .stock-trend {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; margin-right: 6px; }}
  .stock-trend.bull {{ background: rgba(63,185,80,0.15); color: var(--green); }}
  .stock-trend.bear {{ background: rgba(248,81,73,0.15); color: var(--red); }}
  .stock-trend.range {{ background: rgba(210,153,34,0.15); color: var(--yellow); }}
  .signal-card {{ margin-top: 8px; padding: 8px 10px; border-radius: 6px; font-size: 12px; }}
  .signal-card.pending {{ background: rgba(210,153,34,0.08); border: 1px solid rgba(210,153,34,0.2); }}
  .signal-card.completed {{ background: rgba(88,166,255,0.08); border: 1px solid rgba(88,166,255,0.2); }}
  .signal-card .sig-row {{ display: flex; justify-content: space-between; margin-bottom: 2px; }}
  .signal-card .sig-label {{ color: var(--yellow); font-weight: bold; }}
  .signal-card .sig-label.done {{ color: var(--blue); }}
  .signal-card .sig-detail {{ color: var(--text-dim); }}
  .signal-card .sig-strength {{ color: var(--yellow); font-size: 11px; }}
  .signal-card .sig-vwap {{ color: var(--text-dim); font-size: 11px; }}
  .stats-section {{ margin-top: 20px; }}
  .stats-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
  .stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; text-align: center; }}
  .stat-card .stat-label {{ font-size: 12px; color: var(--text-dim); margin-bottom: 4px; }}
  .stat-card .stat-value {{ font-size: 24px; font-weight: bold; }}
  .footer {{ text-align: center; color: #484f58; font-size: 11px; margin-top: 30px; padding-top: 12px; border-top: 1px solid var(--border); }}
  .loading {{ text-align: center; color: var(--text-dim); padding: 40px; font-size: 14px; }}
  @media (max-width: 768px) {{
    body {{ padding: 10px; }}
    .stock-grid {{ grid-template-columns: 1fr; }}
    .status-bar {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>&#x1f4ca; T+0 盯盘仪表盘 <span style="font-size:14px;color:var(--text-dim);">v2.0 动态数据</span></h1>
  <div class="header-right">
    <span class="refresh-info" id="refreshInfo">加载中...</span>
    <button class="refresh-btn" onclick="refreshAll()">&#x21bb; 刷新</button>
  </div>
</div>

<div class="strategy-bar" id="strategyBar"></div>
<div class="status-bar" id="statusBar"></div>

<div style="margin-bottom:20px">
  <div class="section-title">&#x1f4c8; 15只标的实时状态</div>
  <div class="stock-grid" id="stockGrid"><div class="loading">加载数据中...</div></div>
</div>

<div class="stats-section">
  <div class="section-title">&#x1f4cb; 今日T+0战绩</div>
  <div class="stats-cards" id="statsCards"><div class="loading">等待数据...</div></div>
</div>

<div class="footer">
  T+0 日内盯盘系统 v2.0 &middot; VWAP锚定+多信号共振 &middot; 数据来源：westock-data &middot; 仅供参考，不构成投资建议
</div>

<script>
// ═══════════════════════════════════════
// 配置
// ═══════════════════════════════════════
const ALL_CODES = {json.dumps(ALL_CODES)};
const STOCK_NAMES = {json.dumps(STOCK_NAMES, ensure_ascii=False)};
const T0_DISABLED = new Set({json.dumps(list(T0_DISABLED))});
const DATA_URL = "http://localhost:8899/";  // 微静态服务器
const REFRESH_SEC = 30;

// ═══════════════════════════════════════
// 数据获取
// ═══════════════════════════════════════
async function fetchJSON(filename) {{
  try {{
    const resp = await fetch(DATA_URL + filename + "?t=" + Date.now());
    if (!resp.ok) return null;
    return await resp.json();
  }} catch(e) {{ return null; }}
}}

async function fetchAll() {{
  const [heartbeat, snapshot, signals] = await Promise.all([
    fetchJSON("t0-heartbeat.json"),
    fetchJSON("t0-snapshot.json"),
    fetchJSON("t0-signals-today.json"),
  ]);
  return {{ heartbeat, snapshot, signals }};
}}

// ═══════════════════════════════════════
// 渲染
// ═══════════════════════════════════════
function renderStrategyBar(data) {{
  const bar = document.getElementById("strategyBar");
  const sig = data.signals;
  const stocks = sig ? sig.stocks || {{}} : {{}};
  
  let trendCount = {{ BULL: 0, BEAR: 0, RANGE: 0 }};
  let pendingCount = 0;
  let completedCount = 0;
  let totalReturn = 0;
  
  for (const code of ALL_CODES) {{
    const s = stocks[code];
    if (!s) continue;
    if (s.pendingSignal) pendingCount++;
    if (s.completedRounds) {{
      completedCount += s.completedRounds.length;
      s.completedRounds.forEach(r => totalReturn += r.netReturn || 0);
    }}
  }}
  
  bar.innerHTML = `
    <div class="strategy-tag"><span class="label">引擎</span><span class="value">VWAP共振 v2.0</span></div>
    <div class="strategy-tag"><span class="label">已完成</span><span class="value" style="color:var(--blue)">${{completedCount}}轮</span></div>
    <div class="strategy-tag"><span class="label">待配对</span><span class="value" style="color:${{pendingCount > 0 ? 'var(--yellow)' : 'var(--green)'}}">${{pendingCount}}笔</span></div>
    <div class="strategy-tag"><span class="label">总收益</span><span class="value" style="color:${{totalReturn >= 0 ? 'var(--green)' : 'var(--red)'}}">${{totalReturn >= 0 ? '+' : ''}}${{totalReturn.toFixed(2)}}%</span></div>
    <div class="strategy-tag"><span class="label">仓位</span><span class="value">底仓25%</span></div>
    <div class="strategy-tag"><span class="label">止损</span><span class="value" style="color:var(--red)">-1.5%</span></div>
  `;
}}

function renderStatusBar(data) {{
  const bar = document.getElementById("statusBar");
  const hb = data.heartbeat;
  const sig = data.signals;
  const snap = data.snapshot;
  
  // 进程状态
  let procRunning = false;
  let procPid = "--";
  if (hb && hb.pid) {{
    procPid = hb.pid;
    procRunning = hb.timestamp && (Date.now() - new Date(hb.timestamp).getTime()) / 1000 < 360;
  }}
  
  // 心跳新鲜度
  let hbStatus = "gray", hbText = "无数据";
  if (hb && hb.timestamp) {{
    const age = (Date.now() - new Date(hb.timestamp).getTime()) / 1000;
    if (age < 60) {{ hbStatus = "green"; hbText = Math.round(age) + "秒前"; }}
    else if (age < 360) {{ hbStatus = "yellow"; hbText = Math.round(age/60) + "分钟前"; }}
    else {{ hbStatus = "red"; hbText = Math.round(age/60) + "分钟前(失联)"; }}
  }}
  
  // 下次检查
  let nextCheck = "--";
  if (hb && hb.timestamp) {{
    const next = new Date(new Date(hb.timestamp).getTime() + (hb.interval || 300) * 1000);
    const remain = Math.max(0, Math.round((next - Date.now()) / 1000));
    if (remain > 0) nextCheck = "~" + Math.round(remain/60) + "分" + (remain%60) + "秒";
    else nextCheck = "即将";
  }}
  
  // 数据量
  const quoteCount = snap && snap.stocks ? Object.keys(snap.stocks).length : 0;
  
  bar.innerHTML = `
    <div class="status-card">
      <div class="dot ${{procRunning ? 'green pulse' : 'red'}}"></div>
      <div><div class="label">监控进程</div><div class="value">${{procRunning ? '运行 PID:' + procPid : '未运行'}}</div></div>
    </div>
    <div class="status-card">
      <div class="dot ${{hbStatus}}"></div>
      <div><div class="label">心跳</div><div class="value">${{hbText}}</div></div>
    </div>
    <div class="status-card">
      <div class="dot blue"></div>
      <div><div class="label">检查次数 / 行情</div><div class="value">${{hb ? hb.checkCount : '--'}}次 / ${{quoteCount}}只</div></div>
    </div>
    <div class="status-card">
      <div class="dot purple"></div>
      <div><div class="label">下次检查 / 信号</div><div class="value">${{nextCheck}} / ${{hb ? hb.signalCount || 0 : '--'}}个</div></div>
    </div>
  `;
}}

function renderStocks(data) {{
  const grid = document.getElementById("stockGrid");
  const snap = data.snapshot;
  const sig = data.signals;
  
  if (!snap || !snap.stocks) {{
    grid.innerHTML = '<div class="loading">等待行情数据...</div>';
    return;
  }}
  
  let html = "";
  for (const code of ALL_CODES) {{
    const s = snap.stocks[code];
    if (!s) continue;
    
    const name = s.name || STOCK_NAMES[code] || code;
    const price = s.price || 0;
    const change = s.changePercent || 0;
    const high = s.high || 0;
    const low = s.low || 0;
    const isUp = change >= 0;
    const disabled = T0_DISABLED.has(code);
    
    // 信号数据
    const stockState = sig && sig.stocks ? sig.stocks[code] : null;
    const completedRounds = stockState ? stockState.completedRounds || [] : [];
    const pendingSignal = stockState ? stockState.pendingSignal : null;
    
    // 趋势 & VWAP
    let trendHtml = "", trendClass = "";
    if (pendingSignal && pendingSignal.trend) {{
      const t = pendingSignal.trend;
      trendClass = t === "BULL" ? "bull" : t === "BEAR" ? "bear" : "range";
      trendHtml = `<span class="stock-trend ${{trendClass}}">${{t}}</span>`;
    }}
    
    let vwapHtml = "";
    if (pendingSignal && pendingSignal.vwap) {{
      vwapHtml = `<span style="color:var(--text-dim)">VWAP:${{pendingSignal.vwap}}</span>`;
    }}
    
    // 配对完成
    let completedHtml = "";
    completedRounds.forEach(r => {{
      const fc = r.forceclose ? " &#x26a1;" : "";
      const isZheng = r.type === "正T";
      completedHtml += `
        <div class="signal-card completed">
          <div class="sig-row">
            <span class="sig-label done">&#x2705; ${{r.type}}第${{r.round}}轮${{fc}}</span>
            <span style="color:${{r.netReturn >= 0 ? 'var(--green)' : 'var(--red)'}}">${{r.netReturn >= 0 ? '+' : ''}}${{r.netReturn.toFixed(2)}}%</span>
          </div>
          <div class="sig-detail">${{isZheng ? r.buyTime + '买@' + r.buyPrice + ' \u2192 ' + r.sellTime + '卖@' + r.sellPrice : r.sellTime + '卖@' + r.sellPrice + ' \u2192 ' + r.buyTime + '买@' + r.buyPrice}}</div>
        </div>`;
    }});
    
    // 待配对
    let pendingHtml = "";
    if (pendingSignal) {{
      const dirLabel = pendingSignal.signalType === "low" ? "低吸" : "高抛";
      const stars = pendingSignal.strength ? "\u2605".repeat(pendingSignal.strength) + "\u2606".repeat(6 - pendingSignal.strength) : "";
      pendingHtml = `
        <div class="signal-card pending">
          <div class="sig-row">
            <span class="sig-label">&#x23f3; ${{pendingSignal.type}}第${{pendingSignal.round}}轮 等待配对</span>
            <span class="sig-strength">${{stars}}</span>
          </div>
          <div class="sig-detail">${{pendingSignal.time}}${{dirLabel}}@${{pendingSignal.price}} | ${{vwapHtml}} | 入场${{pendingSignal.entryZone || '--'}}</div>
          <div class="sig-detail" style="margin-top:2px;">目标${{pendingSignal.targetZone || '--'}} | 止损${{pendingSignal.stopLoss || '--'}}</div>
        </div>`;
    }}
    
    html += `
    <div class="stock-card ${{disabled ? 'disabled' : ''}}">
      <div class="stock-header">
        <div>
          <span class="stock-name">${{name}}</span>
          <span class="stock-code">${{code}}</span>
          ${{disabled ? '<span style="font-size:11px;color:var(--yellow)">&#x1f507;仅监控</span>' : ''}}
        </div>
        <div style="text-align:right">
          <div class="stock-price" style="color:${{isUp ? 'var(--red)' : 'var(--green)'}}">${{price.toFixed(2)}}</div>
          <div class="stock-change ${{isUp ? 'up' : 'down'}}">${{isUp ? '+' : ''}}${{change.toFixed(2)}}%</div>
        </div>
      </div>
      <div class="stock-meta">${{trendHtml}}高 ${{high.toFixed(2)}} | 低 ${{low.toFixed(2)}} ${{vwapHtml}}</div>
      ${{completedHtml}}
      ${{pendingHtml}}
    </div>`;
  }}
  grid.innerHTML = html;
}}

function renderStats(data) {{
  const el = document.getElementById("statsCards");
  const sig = data.signals;
  
  if (!sig) {{
    el.innerHTML = '<div class="loading">等待数据...</div>';
    return;
  }}
  
  const completed = sig.completedPairs || [];
  const totalPairs = completed.length;
  const totalReturn = completed.reduce((s, p) => s + (p.netReturn || 0), 0);
  const winning = completed.filter(p => (p.netReturn || 0) > 0).length;
  const winRate = totalPairs > 0 ? (winning / totalPairs * 100).toFixed(1) : "--";
  const avgReturn = totalPairs > 0 ? (totalReturn / totalPairs).toFixed(2) : "--";
  
  // 待配对
  let pendingCount = 0;
  const stocks = sig.stocks || {{}};
  for (const code of ALL_CODES) {{
    if (stocks[code] && stocks[code].pendingSignal) pendingCount++;
  }}
  
  // 强制平仓
  const forcedCount = completed.filter(p => p.forceclose).length;
  
  el.innerHTML = `
    <div class="stat-card">
      <div class="stat-label">完成配对</div>
      <div class="stat-value" style="color:var(--blue)">${{totalPairs}}<span style="font-size:14px">轮</span></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">总收益</div>
      <div class="stat-value" style="color:${{totalReturn >= 0 ? 'var(--green)' : 'var(--red)'}}">${{totalReturn >= 0 ? '+' : ''}}${{totalReturn.toFixed(2)}}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">胜率 / 均笔</div>
      <div class="stat-value" style="font-size:20px;color:var(--blue)">${{winRate}}% / ${{avgReturn}}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">待配对 / 强平</div>
      <div class="stat-value" style="color:${{pendingCount > 0 ? 'var(--yellow)' : 'var(--green)'}}">${{pendingCount}}笔 / ${{forcedCount}}笔</div>
    </div>
  `;
}}

function updateRefreshInfo(success) {{
  const el = document.getElementById("refreshInfo");
  const now = new Date();
  const ts = now.toLocaleTimeString("zh-CN");
  if (success) {{
    el.className = "refresh-info";
    el.textContent = "\u2705 " + ts + " | " + REFRESH_SEC + "秒自动刷新";
  }} else {{
    el.className = "refresh-info error";
    el.textContent = "\u274c " + ts + " | 数据加载失败，等待重试...";
  }}
}}

// ═══════════════════════════════════════
// 主循环
// ═══════════════════════════════════════
async function refreshAll() {{
  try {{
    const data = await fetchAll();
    if (data.heartbeat || data.snapshot || data.signals) {{
      renderStrategyBar(data);
      renderStatusBar(data);
      renderStocks(data);
      renderStats(data);
      updateRefreshInfo(true);
    }} else {{
      updateRefreshInfo(false);
    }}
  }} catch(e) {{
    updateRefreshInfo(false);
  }}
}}

refreshAll();
setInterval(refreshAll, REFRESH_SEC * 1000);
</script>
</body>
</html>'''

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard v2.0 generated: {OUTPUT_HTML}")
    return OUTPUT_HTML


if __name__ == "__main__":
    generate_html()
