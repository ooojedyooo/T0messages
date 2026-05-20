#!/usr/bin/env python3
"""
T+0 仪表盘静态页面生成器
功能：读取 data/*.json 数据，生成一个自包含的 dashboard.html
用法：python generate_dashboard.py
      或在 t0_monitor 每次检查后自动调用
"""

import json
import os
import sys
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_SCRIPT_DIR, "data")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")

SIGNALS_FILE = os.path.join(DATA_DIR, "t0-signals-today.json")
HEARTBEAT_FILE = os.path.join(DATA_DIR, "t0-heartbeat.json")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "t0-snapshot.json")
LOG_FILE = os.path.join(DATA_DIR, "t0-monitor.log")
PID_FILE = os.path.join(DATA_DIR, "t0-monitor.pid")
OUTPUT_HTML = os.path.join(REPORTS_DIR, "dashboard.html")

STOCK_NAMES = {
    "sz002594": "比亚迪", "sz300750": "宁德时代", "sh688041": "海光信息",
    "sz300308": "中际旭创", "sz300502": "新易盛", "sh688025": "杰普特",
    "sz002222": "福晶科技", "sz002156": "通富微电", "sh688503": "聚和材料",
    "sh688062": "迈威生物", "sz300660": "江苏雷利", "sh688778": "厦钨新能",
    "sz300450": "先导智能", "sh601208": "东材科技", "sz300014": "亿纬锂能"
}
ALL_CODES = list(STOCK_NAMES.keys())


def safe_read_json(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_system_status():
    status = {"isRunning": False, "pid": None, "processAlive": False}
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = f.read().strip()
            if pid:
                status["pid"] = int(pid)
                import subprocess
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True, text=True, timeout=5
                )
                status["isRunning"] = pid in result.stdout
                status["processAlive"] = status["isRunning"]
        except Exception:
            pass
    return status


def get_recent_logs(n=50):
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-n:]]
    except Exception:
        return []


def generate_html():
    # 读取所有数据
    heartbeat = safe_read_json(HEARTBEAT_FILE)
    snapshot = safe_read_json(SNAPSHOT_FILE)
    signals = safe_read_json(SIGNALS_FILE)
    sys_status = get_system_status()
    logs = get_recent_logs(50)

    # 数据序列化为JSON字符串（嵌入HTML）
    hb_json = json.dumps(heartbeat, ensure_ascii=False)
    snap_json = json.dumps(snapshot, ensure_ascii=False)
    sig_json = json.dumps(signals, ensure_ascii=False)
    status_json = json.dumps(sys_status, ensure_ascii=False)
    logs_json = json.dumps(logs, ensure_ascii=False)

    # 构建时间线检查点
    checkpoints = []
    for h in range(9, 12):
        for m in range(0, 60, 5):
            if h == 11 and m > 30:
                break
            checkpoints.append([h, m])
    for h in range(13, 16):
        for m in range(0, 60, 5):
            if h == 15 and m > 0:
                break
            checkpoints.append([h, m])

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="10">
<title>T+0 盯盘仪表盘</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-dim: #8b949e; --text-bright: #f0f6fc;
    --green: #3fb950; --green-dim: #238636; --red: #f85149; --red-dim: #da3633;
    --blue: #58a6ff; --blue-dim: #1f6feb; --yellow: #d29922; --orange: #d18616;
    --purple: #bc8cff;
  }}
  body {{ font-family: -apple-system, 'Microsoft YaHei', 'PingFang SC', sans-serif; background: var(--bg); color: var(--text); padding: 16px; max-width: 1400px; margin: 0 auto; }}
  .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }}
  .header h1 {{ font-size: 22px; color: var(--blue); display: flex; align-items: center; gap: 8px; }}
  .header h1 .icon {{ font-size: 28px; }}
  .refresh-info {{ font-size: 12px; color: var(--text-dim); }}
  .status-bar {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 20px; }}
  .status-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; display: flex; align-items: center; gap: 12px; }}
  .status-card .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .status-card .dot.green {{ background: var(--green); box-shadow: 0 0 8px var(--green); }}
  .status-card .dot.red {{ background: var(--red); box-shadow: 0 0 8px var(--red); }}
  .status-card .dot.yellow {{ background: var(--yellow); box-shadow: 0 0 8px var(--yellow); }}
  .status-card .dot.gray {{ background: #484f58; }}
  .status-card .dot.blue {{ background: var(--blue); }}
  .status-card .dot.purple {{ background: var(--purple); }}
  .status-card .label {{ font-size: 12px; color: var(--text-dim); }}
  .status-card .value {{ font-size: 16px; font-weight: bold; color: var(--text-bright); }}
  .pulse {{ animation: pulse 2s infinite; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
  .timeline-section {{ margin-bottom: 20px; }}
  .timeline-section h2 {{ color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; display: flex; align-items: center; gap: 6px; }}
  .timeline {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .timeline .tick {{ width: 8px; height: 24px; border-radius: 3px; position: relative; cursor: default; }}
  .timeline .tick.signal {{ background: var(--green); }}
  .timeline .tick.no-signal {{ background: var(--blue-dim); opacity: 0.6; }}
  .timeline .tick.error {{ background: var(--red); }}
  .timeline .tick.idle {{ background: #21262d; }}
  .tick-legend {{ display: flex; gap: 14px; margin-top: 8px; font-size: 12px; color: var(--text-dim); }}
  .tick-legend span {{ display: flex; align-items: center; gap: 4px; }}
  .tick-legend .sq {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}
  .stocks-section h2 {{ color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  .stock-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 10px; }}
  .stock-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; transition: border-color 0.2s; }}
  .stock-card:hover {{ border-color: var(--blue); }}
  .stock-card .stock-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .stock-card .stock-name {{ font-size: 15px; font-weight: bold; color: var(--text-bright); }}
  .stock-card .stock-code {{ font-size: 11px; color: var(--text-dim); }}
  .stock-card .stock-price {{ font-size: 20px; font-weight: bold; }}
  .stock-card .stock-change {{ font-size: 13px; font-weight: bold; padding: 2px 6px; border-radius: 4px; }}
  .stock-card .stock-change.up {{ color: var(--red); background: rgba(248,81,73,0.1); }}
  .stock-card .stock-change.down {{ color: var(--green); background: rgba(63,185,80,0.1); }}
  .stock-card .stock-range {{ font-size: 11px; color: var(--text-dim); margin-top: 2px; }}
  .stock-card .stock-indicators {{ display: flex; gap: 10px; margin-top: 6px; font-size: 12px; color: var(--text-dim); }}
  .stock-card .stock-indicators span {{ display: flex; align-items: center; gap: 3px; }}
  .signal-tags {{ margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }}
  .signal-tag {{ font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 500; }}
  .signal-tag.low {{ background: rgba(63,185,80,0.15); color: var(--green); border: 1px solid rgba(63,185,80,0.3); }}
  .signal-tag.high {{ background: rgba(248,81,73,0.15); color: var(--red); border: 1px solid rgba(248,81,73,0.3); }}
  .signal-tag.paired {{ background: rgba(88,166,255,0.15); color: var(--blue); border: 1px solid rgba(88,166,255,0.3); }}
  .signal-tag.pending {{ background: rgba(210,153,34,0.15); color: var(--yellow); border: 1px solid rgba(210,153,34,0.3); }}
  .pair-info {{ margin-top: 6px; font-size: 12px; padding: 6px 8px; background: rgba(88,166,255,0.08); border-radius: 4px; }}
  .pair-info .pair-label {{ color: var(--blue); font-weight: 500; }}
  .pair-info .pair-detail {{ color: var(--text-dim); }}
  .pending-info {{ margin-top: 6px; font-size: 12px; padding: 6px 8px; background: rgba(210,153,34,0.08); border-radius: 4px; }}
  .pending-info .pending-label {{ color: var(--yellow); font-weight: 500; }}
  .pending-info .pending-detail {{ color: var(--text-dim); }}
  .pending-info .targets {{ margin-top: 4px; font-size: 11px; color: var(--text-dim); }}
  .stats-section {{ margin-top: 20px; }}
  .stats-section h2 {{ color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  .stats-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
  .stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; text-align: center; }}
  .stat-card .stat-label {{ font-size: 12px; color: var(--text-dim); margin-bottom: 4px; }}
  .stat-card .stat-value {{ font-size: 24px; font-weight: bold; }}
  .log-section {{ margin-top: 20px; }}
  .log-section h2 {{ color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; display: flex; align-items: center; gap: 6px; }}
  .log-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px; max-height: 300px; overflow-y: auto; font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 11px; line-height: 1.6; color: var(--text-dim); }}
  .log-box .log-line.signal-line {{ color: var(--green); }}
  .log-box .log-line.error-line {{ color: var(--red); }}
  .log-box .log-line.warn-line {{ color: var(--yellow); }}
  .footer {{ text-align: center; color: #484f58; font-size: 11px; margin-top: 30px; padding-top: 12px; border-top: 1px solid var(--border); }}
  .no-data {{ color: var(--text-dim); font-size: 13px; padding: 20px; }}
  @media (max-width: 768px) {{
    body {{ padding: 10px; }}
    .stock-grid {{ grid-template-columns: 1fr; }}
    .status-bar {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1><span class="icon">📊</span> T+0 盯盘仪表盘</h1>
  <div class="refresh-info" id="refreshInfo">最后生成：{datetime.now().strftime('%H:%M:%S')} | 每10秒自动刷新</div>
</div>

<div class="status-bar" id="statusBar"></div>

<div class="timeline-section">
  <h2>🕐 检查时间线</h2>
  <div class="timeline" id="timeline"></div>
  <div class="tick-legend">
    <span><span class="sq" style="background:var(--green)"></span>有信号</span>
    <span><span class="sq" style="background:var(--blue-dim);opacity:0.6"></span>无信号</span>
    <span><span class="sq" style="background:var(--red)"></span>异常</span>
    <span><span class="sq" style="background:#21262d"></span>未检查</span>
  </div>
</div>

<div class="stocks-section">
  <h2>📈 15只标的实时状态</h2>
  <div class="stock-grid" id="stockGrid"></div>
</div>

<div class="stats-section">
  <h2>📋 今日T+0战绩</h2>
  <div class="stats-cards" id="statsCards"></div>
</div>

<div class="log-section">
  <h2>📝 运行日志（最近50条）</h2>
  <div class="log-box" id="logBox"></div>
</div>

<div class="footer">T+0 日内盯盘系统 · 数据来源：westock-data · 仅供参考，不构成投资建议</div>

<script>
const ALL_CODES = {json.dumps(ALL_CODES)};
const STOCK_NAMES = {json.dumps(STOCK_NAMES, ensure_ascii=False)};
const CHECKPOINTS = {json.dumps(checkpoints)};

const heartbeat = {hb_json};
const snapshot = {snap_json};
const signals = {sig_json};
const sysStatus = {status_json};
const logs = {logs_json};

function renderStatusBar() {{
  const bar = document.getElementById('statusBar');
  const isRunning = sysStatus.isRunning;

  let hbStatus = 'gray';
  let hbText = '无心跳数据';
  if (heartbeat && heartbeat.timestamp) {{
    const age = (Date.now() - new Date(heartbeat.timestamp).getTime()) / 1000;
    if (age < 60) {{ hbStatus = 'green'; hbText = `${{Math.round(age)}}秒前`; }}
    else if (age < 360) {{ hbStatus = 'yellow'; hbText = `${{Math.round(age/60)}}分钟前（延迟）`; }}
    else {{ hbStatus = 'red'; hbText = `${{Math.round(age/60)}}分钟前（失联）`; }}
  }}

  let nextCheck = '--';
  if (heartbeat && heartbeat.timestamp) {{
    const next = new Date(new Date(heartbeat.timestamp).getTime() + (heartbeat.interval || 300) * 1000);
    const remain = Math.max(0, Math.round((next - Date.now()) / 1000));
    if (remain > 0) nextCheck = `~${{Math.round(remain/60)}}分${{remain%60}}秒`;
    else nextCheck = '即将检查';
  }}

  bar.innerHTML = `
    <div class="status-card">
      <div class="dot ${{isRunning ? 'green pulse' : 'red'}}"></div>
      <div>
        <div class="label">监控进程</div>
        <div class="value">${{isRunning ? '运行中 (PID:' + sysStatus.pid + ')' : '未运行'}}</div>
      </div>
    </div>
    <div class="status-card">
      <div class="dot ${{hbStatus}}"></div>
      <div>
        <div class="label">最近心跳</div>
        <div class="value">${{hbText}}</div>
      </div>
    </div>
    <div class="status-card">
      <div class="dot blue"></div>
      <div>
        <div class="label">检查次数</div>
        <div class="value">${{heartbeat ? heartbeat.checkCount : '--'}}</div>
      </div>
    </div>
    <div class="status-card">
      <div class="dot purple"></div>
      <div>
        <div class="label">下次检查</div>
        <div class="value">${{nextCheck}}</div>
      </div>
    </div>
  `;
}}

function renderTimeline() {{
  const tl = document.getElementById('timeline');
  if (!heartbeat || !heartbeat.timestamp) {{
    tl.innerHTML = '<span class="no-data">等待数据...</span>';
    return;
  }}

  const signalTimes = new Set();
  if (signals && signals.allSignals) {{
    signals.allSignals.forEach(s => signalTimes.add(s.time));
  }}

  const now = new Date();
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  let html = '';

  for (const [h, m] of CHECKPOINTS) {{
    const cpMinutes = h * 60 + m;
    const timeStr = String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0');
    if (cpMinutes > nowMinutes) break;

    let type = 'no-signal';
    if (signalTimes.has(timeStr)) type = 'signal';

    html += `<div class="tick ${{type}}" title="${{timeStr}} ${{type === 'signal' ? '有信号' : '无信号'}}"></div>`;
  }}
  tl.innerHTML = html || '<span class="no-data">等待数据...</span>';
}}

function renderStocks() {{
  const grid = document.getElementById('stockGrid');
  if (!snapshot || !snapshot.stocks) {{
    grid.innerHTML = '<span class="no-data">等待行情数据...</span>';
    return;
  }}

  let html = '';
  for (const code of ALL_CODES) {{
    const s = snapshot.stocks[code];
    if (!s) continue;

    const name = s.name || STOCK_NAMES[code] || code;
    const price = s.price || 0;
    const change = s.changePercent || 0;
    const high = s.high || 0;
    const low = s.low || 0;
    const rsi6 = s.rsi6;
    const mainNet = s.mainNetFlow;
    const isUp = change >= 0;

    const stockState = signals && signals.stocks && signals.stocks[code];
    const completedRounds = stockState ? stockState.completedRounds || [] : [];
    const pendingSignal = stockState ? stockState.pendingSignal : null;
    const allStockSignals = signals && signals.allSignals ? signals.allSignals.filter(sig => sig.code === code) : [];

    let tagsHtml = '';
    allStockSignals.forEach(sig => {{
      const dir = sig.type === 'low' ? '🟢低吸' : '🔴高抛';
      tagsHtml += `<span class="signal-tag ${{sig.type}}">${{dir}} ${{sig.time}} @${{sig.price}} ${{sig.details || ''}}</span>`;
    }});

    let pairHtml = '';
    completedRounds.forEach(r => {{
      if (r.type === '正T') {{
        pairHtml += `<div class="pair-info"><span class="pair-label">&#9989; 正T第${{r.round}}轮</span> <span class="pair-detail">${{r.buyTime}}买@${{r.buyPrice}} &rarr; ${{r.sellTime}}卖@${{r.sellPrice}} 净+${{r.netReturn.toFixed(2)}}%</span></div>`;
      }} else {{
        pairHtml += `<div class="pair-info"><span class="pair-label">&#9989; 反T第${{r.round}}轮</span> <span class="pair-detail">${{r.sellTime}}卖@${{r.sellPrice}} &rarr; ${{r.buyTime}}买@${{r.buyPrice}} 净+${{r.netReturn.toFixed(2)}}%</span></div>`;
      }}
    }});

    let pendingHtml = '';
    if (pendingSignal) {{
      const dir = pendingSignal.signalType === 'low' ? '低吸' : '高抛';
      const t = pendingSignal.type;
      const targets = pendingSignal.targets || {{}};
      pendingHtml = `<div class="pending-info">
        <span class="pending-label">&#9203; ${{t}}第${{pendingSignal.round}}轮 &middot; 等待配对</span>
        <span class="pending-detail"> | ${{pendingSignal.time}}${{dir}}@${{pendingSignal.price}}</span>
        ${{targets.min ? `<div class="targets">&#127919; 目标位：最低${{targets.min}}(+${{targets.min_pct}}%) | 合理${{targets.reasonable}}(+${{targets.reasonable_pct}}%)</div>` : ''}}
      </div>`;
    }}

    html += `
    <div class="stock-card">
      <div class="stock-header">
        <div>
          <span class="stock-name">${{name}}</span>
          <span class="stock-code">${{code}}</span>
        </div>
        <div style="text-align:right">
          <div class="stock-price" style="color:${{isUp ? 'var(--red)' : 'var(--green)'}}">${{price.toFixed(2)}}</div>
          <div class="stock-change ${{isUp ? 'up' : 'down'}}">${{isUp ? '+' : ''}}${{change.toFixed(2)}}%</div>
        </div>
      </div>
      <div class="stock-range">高 ${{high.toFixed(2)}} | 低 ${{low.toFixed(2)}}</div>
      <div class="stock-indicators">
        ${{rsi6 !== null && rsi6 !== undefined ? `<span>RSI6: <b style="color:${{rsi6 < 35 ? 'var(--green)' : rsi6 > 65 ? 'var(--red)' : 'var(--text)'}}">${{rsi6.toFixed(1)}}</b></span>` : ''}}
        ${{mainNet !== null && mainNet !== undefined ? `<span>主力: <b style="color:${{mainNet > 0 ? 'var(--red)' : 'var(--green)'}}">${{(mainNet/10000).toFixed(0)}}万</b></span>` : ''}}
      </div>
      ${{tagsHtml ? `<div class="signal-tags">${{tagsHtml}}</div>` : ''}}
      ${{pairHtml}}
      ${{pendingHtml}}
    </div>`;
  }}
  grid.innerHTML = html;
}}

function renderStats() {{
  const el = document.getElementById('statsCards');
  if (!signals) {{
    el.innerHTML = '<span class="no-data">等待数据...</span>';
    return;
  }}

  const completed = signals.completedPairs || [];
  const allSigs = signals.allSignals || [];
  const totalPairs = completed.length;
  const totalReturn = completed.reduce((s, p) => s + (p.netReturn || 0), 0);
  const winning = completed.filter(p => (p.netReturn || 0) > 0).length;
  const winRate = totalPairs > 0 ? (winning / totalPairs * 100).toFixed(0) : '--';
  const lowCount = allSigs.filter(s => s.type === 'low').length;
  const highCount = allSigs.filter(s => s.type === 'high').length;
  const pendingCount = Object.values(signals.stocks || {{}}).filter(s => s.pendingSignal).length;

  el.innerHTML = `
    <div class="stat-card">
      <div class="stat-label">完成配对</div>
      <div class="stat-value" style="color:var(--blue)">${{totalPairs}}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">预估总收益</div>
      <div class="stat-value" style="color:${{totalReturn > 0 ? 'var(--green)' : totalReturn < 0 ? 'var(--red)' : 'var(--text)'}}">${{totalReturn > 0 ? '+' : ''}}${{totalReturn.toFixed(2)}}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">胜率</div>
      <div class="stat-value" style="color:var(--blue)">${{winRate}}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">信号次数</div>
      <div class="stat-value" style="color:var(--blue);font-size:18px">&#128308;${{lowCount}} &#128997;${{highCount}}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">待配对</div>
      <div class="stat-value" style="color:var(--yellow)">${{pendingCount}}</div>
    </div>
  `;
}}

function renderLogs() {{
  const box = document.getElementById('logBox');
  if (!logs || logs.length === 0) {{
    box.innerHTML = '<span class="no-data">暂无日志</span>';
    return;
  }}
  box.innerHTML = logs.map(l => {{
    let cls = 'log-line';
    if (l.includes('信号') || l.includes('配对')) cls += ' signal-line';
    else if (l.includes('异常') || l.includes('错误') || l.includes('&#9888;')) cls += ' error-line';
    else if (l.includes('跳过') || l.includes('非交易')) cls += ' warn-line';
    return `<div class="${{cls}}">${{l}}</div>`;
  }}).join('');
  box.scrollTop = box.scrollHeight;
}}

renderStatusBar();
renderTimeline();
renderStocks();
renderStats();
renderLogs();
</script>
</body>
</html>'''

    # 确保 reports 目录存在
    os.makedirs(REPORTS_DIR, exist_ok=True)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard generated: {OUTPUT_HTML}")
    return OUTPUT_HTML


if __name__ == "__main__":
    generate_html()
