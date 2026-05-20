#!/usr/bin/env python3
"""
T+0 盯盘仪表盘 - 本地Web服务器
功能：启动一个轻量HTTP服务器，提供实时仪表盘页面和数据API
用法：python dashboard_server.py [--port 8899]
"""

import json
import os
import sys
import argparse
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

# 数据目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_SCRIPT_DIR, "data")

SIGNALS_FILE = os.path.join(DATA_DIR, "t0-signals-today.json")
HEARTBEAT_FILE = os.path.join(DATA_DIR, "t0-heartbeat.json")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "t0-snapshot.json")
LOG_FILE = os.path.join(DATA_DIR, "t0-monitor.log")
PID_FILE = os.path.join(DATA_DIR, "t0-monitor.pid")

STOCK_NAMES = {
    "sz002594": "比亚迪", "sz300750": "宁德时代", "sh688041": "海光信息",
    "sz300308": "中际旭创", "sz300502": "新易盛", "sh688025": "杰普特",
    "sz002222": "福晶科技", "sz002156": "通富微电", "sh688503": "聚和材料",
    "sh688062": "迈威生物", "sz300660": "江苏雷利", "sh688778": "厦钨新能",
    "sz300450": "先导智能", "sh601208": "东材科技", "sz300014": "亿纬锂能"
}
ALL_CODES = list(STOCK_NAMES.keys())


def safe_read_json(filepath):
    """安全读取JSON文件"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_system_status():
    """获取系统运行状态"""
    status = {
        "isRunning": False,
        "pid": None,
        "processAlive": False,
    }
    # 检查PID文件
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = f.read().strip()
            if pid:
                status["pid"] = int(pid)
                # 检查进程是否存活
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
    """读取最近N条日志"""
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-n:]]
    except Exception:
        return []


# HTML仪表盘页面（自包含）
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>T+0 盯盘仪表盘</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-dim: #8b949e; --text-bright: #f0f6fc;
    --green: #3fb950; --green-dim: #238636; --red: #f85149; --red-dim: #da3633;
    --blue: #58a6ff; --blue-dim: #1f6feb; --yellow: #d29922; --orange: #d18616;
    --purple: #bc8cff;
  }
  body { font-family: -apple-system, 'Microsoft YaHei', 'PingFang SC', sans-serif; background: var(--bg); color: var(--text); padding: 16px; }
  .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }
  .header h1 { font-size: 22px; color: var(--blue); display: flex; align-items: center; gap: 8px; }
  .header h1 .icon { font-size: 28px; }
  .refresh-info { font-size: 12px; color: var(--text-dim); }

  /* 状态条 */
  .status-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 20px; }
  .status-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; display: flex; align-items: center; gap: 12px; }
  .status-card .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .status-card .dot.green { background: var(--green); box-shadow: 0 0 8px var(--green); }
  .status-card .dot.red { background: var(--red); box-shadow: 0 0 8px var(--red); }
  .status-card .dot.yellow { background: var(--yellow); box-shadow: 0 0 8px var(--yellow); }
  .status-card .dot.gray { background: #484f58; }
  .status-card .label { font-size: 12px; color: var(--text-dim); }
  .status-card .value { font-size: 16px; font-weight: bold; color: var(--text-bright); }
  .pulse { animation: pulse 2s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

  /* 检查时间线 */
  .timeline-section { margin-bottom: 20px; }
  .timeline-section h2 { color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; display: flex; align-items: center; gap: 6px; }
  .timeline { display: flex; gap: 4px; flex-wrap: wrap; }
  .timeline .tick { width: 8px; height: 24px; border-radius: 3px; position: relative; cursor: default; }
  .timeline .tick.signal { background: var(--green); }
  .timeline .tick.no-signal { background: var(--blue-dim); opacity: 0.6; }
  .timeline .tick.error { background: var(--red); }
  .timeline .tick.idle { background: #21262d; }
  .timeline .tick:hover::after { content: attr(data-tip); position: absolute; bottom: 28px; left: 50%; transform: translateX(-50%); background: #000; color: #fff; padding: 3px 8px; border-radius: 4px; font-size: 11px; white-space: nowrap; z-index: 99; }
  .tick-legend { display: flex; gap: 14px; margin-top: 8px; font-size: 12px; color: var(--text-dim); }
  .tick-legend span { display: flex; align-items: center; gap: 4px; }
  .tick-legend .sq { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }

  /* 股票分组卡片 */
  .stocks-section h2 { color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  .stock-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 10px; }
  .stock-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; transition: border-color 0.2s; }
  .stock-card:hover { border-color: var(--blue); }
  .stock-card .stock-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .stock-card .stock-name { font-size: 15px; font-weight: bold; color: var(--text-bright); }
  .stock-card .stock-code { font-size: 11px; color: var(--text-dim); }
  .stock-card .stock-price { font-size: 20px; font-weight: bold; }
  .stock-card .stock-change { font-size: 13px; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
  .stock-card .stock-change.up { color: var(--red); background: rgba(248,81,73,0.1); }
  .stock-card .stock-change.down { color: var(--green); background: rgba(63,185,80,0.1); }
  .stock-card .stock-range { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
  .stock-card .stock-indicators { display: flex; gap: 10px; margin-top: 6px; font-size: 12px; color: var(--text-dim); }
  .stock-card .stock-indicators span { display: flex; align-items: center; gap: 3px; }

  /* 信号标签 */
  .signal-tags { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
  .signal-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 500; }
  .signal-tag.low { background: rgba(63,185,80,0.15); color: var(--green); border: 1px solid rgba(63,185,80,0.3); }
  .signal-tag.high { background: rgba(248,81,73,0.15); color: var(--red); border: 1px solid rgba(248,81,73,0.3); }
  .signal-tag.paired { background: rgba(88,166,255,0.15); color: var(--blue); border: 1px solid rgba(88,166,255,0.3); }
  .signal-tag.pending { background: rgba(210,153,34,0.15); color: var(--yellow); border: 1px solid rgba(210,153,34,0.3); }

  /* 配对信息 */
  .pair-info { margin-top: 6px; font-size: 12px; padding: 6px 8px; background: rgba(88,166,255,0.08); border-radius: 4px; }
  .pair-info .pair-label { color: var(--blue); font-weight: 500; }
  .pair-info .pair-detail { color: var(--text-dim); }

  /* 待配对信息 */
  .pending-info { margin-top: 6px; font-size: 12px; padding: 6px 8px; background: rgba(210,153,34,0.08); border-radius: 4px; }
  .pending-info .pending-label { color: var(--yellow); font-weight: 500; }
  .pending-info .pending-detail { color: var(--text-dim); }
  .pending-info .targets { margin-top: 4px; font-size: 11px; color: var(--text-dim); }

  /* 战绩统计 */
  .stats-section { margin-top: 20px; }
  .stats-section h2 { color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  .stats-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
  .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; text-align: center; }
  .stat-card .stat-label { font-size: 12px; color: var(--text-dim); margin-bottom: 4px; }
  .stat-card .stat-value { font-size: 24px; font-weight: bold; }

  /* 日志 */
  .log-section { margin-top: 20px; }
  .log-section h2 { color: var(--blue); font-size: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; cursor: pointer; display: flex; align-items: center; gap: 6px; }
  .log-box { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px; max-height: 200px; overflow-y: auto; font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 11px; line-height: 1.6; color: var(--text-dim); }
  .log-box .log-line.signal-line { color: var(--green); }
  .log-box .log-line.error-line { color: var(--red); }
  .log-box .log-line.warn-line { color: var(--yellow); }

  .footer { text-align: center; color: #484f58; font-size: 11px; margin-top: 30px; padding-top: 12px; border-top: 1px solid var(--border); }

  /* 响应式 */
  @media (max-width: 768px) {
    body { padding: 10px; }
    .stock-grid { grid-template-columns: 1fr; }
    .status-bar { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>
<div class="header">
  <h1><span class="icon">📊</span> T+0 盯盘仪表盘</h1>
  <div class="refresh-info" id="refreshInfo">加载中...</div>
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
// ═══════════════════════════════════════
// 配置
// ═══════════════════════════════════════
const REFRESH_INTERVAL = 5000; // 5秒刷新
const ALL_CODES = ["sz002594","sz300750","sh688041","sz300308","sz300502","sh688025","sz002222","sz002156","sh688503","sh688062","sz300660","sh688778","sz300450","sh601208","sz300014"];
const STOCK_NAMES = {"sz002594":"比亚迪","sz300750":"宁德时代","sh688041":"海光信息","sz300308":"中际旭创","sz300502":"新易盛","sh688025":"杰普特","sz002222":"福晶科技","sz002156":"通富微电","sh688503":"聚和材料","sh688062":"迈威生物","sz300660":"江苏雷利","sh688778":"厦钨新能","sz300450":"先导智能","sh601208":"东材科技","sz300014":"亿纬锂能"};

let lastHeartbeat = null;
let checkTimeline = []; // [{time, type}]

// ═══════════════════════════════════════
// 数据获取
// ═══════════════════════════════════════
async function fetchJSON(url) {
  try {
    const r = await fetch(url + '?t=' + Date.now());
    if (!r.ok) return null;
    return await r.json();
  } catch(e) { return null; }
}

async function fetchText(url) {
  try {
    const r = await fetch(url + '?t=' + Date.now());
    if (!r.ok) return '';
    return await r.text();
  } catch(e) { return ''; }
}

// ═══════════════════════════════════════
// 渲染
// ═══════════════════════════════════════
function renderStatusBar(sysStatus, heartbeat) {
  const bar = document.getElementById('statusBar');
  const isRunning = sysStatus.isRunning;
  const hb = heartbeat;

  // 心跳新鲜度：30秒内有更新=正常，5分钟内=延迟，超过5分钟=失联
  let hbStatus = 'gray';
  let hbText = '无心跳数据';
  if (hb && hb.timestamp) {
    const age = (Date.now() - new Date(hb.timestamp).getTime()) / 1000;
    if (age < 60) { hbStatus = 'green'; hbText = `${Math.round(age)}秒前`; }
    else if (age < 360) { hbStatus = 'yellow'; hbText = `${Math.round(age/60)}分钟前（延迟）`; }
    else { hbStatus = 'red'; hbText = `${Math.round(age/60)}分钟前（失联）`; }
  }

  // 下次检查倒计时
  let nextCheck = '--';
  if (hb && hb.timestamp) {
    const next = new Date(new Date(hb.timestamp).getTime() + 300000);
    const remain = Math.max(0, Math.round((next - Date.now()) / 1000));
    if (remain > 0) nextCheck = `~${Math.round(remain/60)}分${remain%60}秒`;
    else nextCheck = '即将检查';
  }

  bar.innerHTML = `
    <div class="status-card">
      <div class="dot ${isRunning ? 'green pulse' : 'red'}"></div>
      <div>
        <div class="label">监控进程</div>
        <div class="value">${isRunning ? '运行中 (PID:' + sysStatus.pid + ')' : '未运行'}</div>
      </div>
    </div>
    <div class="status-card">
      <div class="dot ${hbStatus}"></div>
      <div>
        <div class="label">最近心跳</div>
        <div class="value">${hbText}</div>
      </div>
    </div>
    <div class="status-card">
      <div class="dot blue" style="background:var(--blue)"></div>
      <div>
        <div class="label">检查次数</div>
        <div class="value">${hb ? hb.checkCount : '--'}</div>
      </div>
    </div>
    <div class="status-card">
      <div class="dot" style="background:var(--purple)"></div>
      <div>
        <div class="label">下次检查</div>
        <div class="value">${nextCheck}</div>
      </div>
    </div>
  `;
}

function renderTimeline(heartbeat, signals) {
  const tl = document.getElementById('timeline');
  // 从日志中提取检查记录
  // 简化方案：用信号时间 + 心跳时间推算
  // 每次心跳视为一次检查点
  if (!heartbeat || !heartbeat.timestamp) {
    tl.innerHTML = '<span style="color:var(--text-dim);font-size:13px;">等待数据...</span>';
    return;
  }

  // 收集检查点（从allSignals的时间去重）
  let checkTimes = new Set();
  if (signals && signals.allSignals) {
    signals.allSignals.forEach(s => checkTimes.add(s.time));
  }

  // 交易时段检查点（9:30-11:30, 13:00-15:00，每5分钟）
  const now = new Date();
  const today = now.toISOString().slice(0,10);
  const checkpoints = [];
  const sessions = [[9,30],[9,35],[9,40],[9,45],[9,50],[9,55],[10,0],[10,5],[10,10],[10,15],[10,20],[10,25],[10,30],[10,35],[10,40],[10,45],[10,50],[10,55],[11,0],[11,5],[11,10],[11,15],[11,20],[11,25],[11,30],
                    [13,0],[13,5],[13,10],[13,15],[13,20],[13,25],[13,30],[13,35],[13,40],[13,45],[13,50],[13,55],[14,0],[14,5],[14,10],[14,15],[14,20],[14,25],[14,30],[14,35],[14,40],[14,45],[14,50],[14,55],[15,0]];

  const hbTime = heartbeat.timestamp ? new Date(heartbeat.timestamp) : null;
  const signalTimes = new Set();
  if (signals && signals.allSignals) {
    signals.allSignals.forEach(s => signalTimes.add(s.time));
  }

  // 判断每个检查点的状态
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  let html = '';
  for (const [h, m] of checkpoints) {
    const cpMinutes = h * 60 + m;
    const timeStr = String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0');
    if (cpMinutes > nowMinutes) break; // 未来的检查点不显示

    // 判断这个检查点是否有信号
    let type = 'idle'; // 默认未检查
    if (hbTime) {
      // 如果心跳时间在这个检查点之后，说明已检查过
      if (signalTimes.has(timeStr)) {
        type = 'signal';
      } else {
        // 检查是否在心跳之前（说明已检查过）
        // 简化：如果当前时间已过此检查点且系统在运行，视为已检查
        type = 'no-signal';
      }
    }

    // 从allSignals判断哪些时间点有信号
    const hasSignalAtTime = signals && signals.allSignals && signals.allSignals.some(s => s.time === timeStr);
    if (hasSignalAtTime) type = 'signal';

    html += `<div class="tick ${type}" data-tip="${timeStr} ${type === 'signal' ? '有信号' : type === 'no-signal' ? '无信号' : type === 'error' ? '异常' : '待检查'}"></div>`;
  }
  tl.innerHTML = html || '<span style="color:var(--text-dim);font-size:13px;">等待数据...</span>';
}

function renderStocks(snapshot, signals) {
  const grid = document.getElementById('stockGrid');
  if (!snapshot || !snapshot.stocks) {
    grid.innerHTML = '<span style="color:var(--text-dim);">等待行情数据...</span>';
    return;
  }

  let html = '';
  for (const code of ALL_CODES) {
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

    // 获取该股票的信号状态
    const stockState = signals && signals.stocks && signals.stocks[code];
    const completedRounds = stockState ? stockState.completedRounds || [] : [];
    const pendingSignal = stockState ? stockState.pendingSignal : null;
    const allStockSignals = signals && signals.allSignals ? signals.allSignals.filter(sig => sig.code === code) : [];

    // 信号标签
    let tagsHtml = '';
    allStockSignals.forEach(sig => {
      const dir = sig.type === 'low' ? '🟢低吸' : '🔴高抛';
      tagsHtml += `<span class="signal-tag ${sig.type}">${dir} ${sig.time} @${sig.price} ${sig.details}</span>`;
    });

    // 配对信息
    let pairHtml = '';
    completedRounds.forEach(r => {
      if (r.type === '正T') {
        pairHtml += `<div class="pair-info"><span class="pair-label">✅ 正T第${r.round}轮</span> <span class="pair-detail">${r.buyTime}买@${r.buyPrice} → ${r.sellTime}卖@${r.sellPrice} 净+${r.netReturn.toFixed(2)}%</span></div>`;
      } else {
        pairHtml += `<div class="pair-info"><span class="pair-label">✅ 反T第${r.round}轮</span> <span class="pair-detail">${r.sellTime}卖@${r.sellPrice} → ${r.buyTime}买@${r.buyPrice} 净+${r.netReturn.toFixed(2)}%</span></div>`;
      }
    });

    // 待配对信息
    let pendingHtml = '';
    if (pendingSignal) {
      const dir = pendingSignal.signalType === 'low' ? '低吸' : '高抛';
      const t = pendingSignal.type;
      const targets = pendingSignal.targets || {};
      pendingHtml = `<div class="pending-info">
        <span class="pending-label">⏳ ${t}第${pendingSignal.round}轮 · 等待配对</span>
        <span class="pending-detail"> | ${pendingSignal.time}${dir}@${pendingSignal.price}</span>
        ${targets.min ? `<div class="targets">🎯 目标位：最低${targets.min}(+${targets.min_pct}%) | 合理${targets.reasonable}(+${targets.reasonable_pct}%)</div>` : ''}
      </div>`;
    }

    html += `
    <div class="stock-card">
      <div class="stock-header">
        <div>
          <span class="stock-name">${name}</span>
          <span class="stock-code">${code}</span>
        </div>
        <div style="text-align:right">
          <div class="stock-price" style="color:${isUp ? 'var(--red)' : 'var(--green)'}">${price.toFixed(2)}</div>
          <div class="stock-change ${isUp ? 'up' : 'down'}">${isUp ? '+' : ''}${change.toFixed(2)}%</div>
        </div>
      </div>
      <div class="stock-range">高 ${high.toFixed(2)} | 低 ${low.toFixed(2)}</div>
      <div class="stock-indicators">
        ${rsi6 !== null && rsi6 !== undefined ? `<span>RSI6: <b style="color:${rsi6 < 35 ? 'var(--green)' : rsi6 > 65 ? 'var(--red)' : 'var(--text)'}">${rsi6.toFixed(1)}</b></span>` : ''}
        ${mainNet !== null && mainNet !== undefined ? `<span>主力: <b style="color:${mainNet > 0 ? 'var(--red)' : 'var(--green)'}">${(mainNet/10000).toFixed(0)}万</b></span>` : ''}
      </div>
      ${tagsHtml ? `<div class="signal-tags">${tagsHtml}</div>` : ''}
      ${pairHtml}
      ${pendingHtml}
    </div>`;
  }
  grid.innerHTML = html;
}

function renderStats(signals) {
  const el = document.getElementById('statsCards');
  if (!signals) {
    el.innerHTML = '<span style="color:var(--text-dim);">等待数据...</span>';
    return;
  }

  const completed = signals.completedPairs || [];
  const allSigs = signals.allSignals || [];
  const totalPairs = completed.length;
  const totalReturn = completed.reduce((s, p) => s + (p.netReturn || 0), 0);
  const winning = completed.filter(p => (p.netReturn || 0) > 0).length;
  const winRate = totalPairs > 0 ? (winning / totalPairs * 100).toFixed(0) : '--';
  const lowCount = allSigs.filter(s => s.type === 'low').length;
  const highCount = allSigs.filter(s => s.type === 'high').length;
  const pendingCount = Object.values(signals.stocks || {}).filter(s => s.pendingSignal).length;

  el.innerHTML = `
    <div class="stat-card">
      <div class="stat-label">完成配对</div>
      <div class="stat-value" style="color:var(--blue)">${totalPairs}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">预估总收益</div>
      <div class="stat-value" style="color:${totalReturn > 0 ? 'var(--green)' : totalReturn < 0 ? 'var(--red)' : 'var(--text)'}">${totalReturn > 0 ? '+' : ''}${totalReturn.toFixed(2)}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">胜率</div>
      <div class="stat-value" style="color:var(--blue)">${winRate}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">信号次数</div>
      <div class="stat-value" style="color:var(--blue)">🟢${lowCount} 🔴${highCount}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">待配对</div>
      <div class="stat-value" style="color:var(--yellow)">${pendingCount}</div>
    </div>
  `;
}

function renderLogs(logText) {
  const box = document.getElementById('logBox');
  if (!logText) {
    box.innerHTML = '<span style="color:var(--text-dim);">暂无日志</span>';
    return;
  }
  const lines = logText.trim().split('\n').slice(-50);
  box.innerHTML = lines.map(l => {
    let cls = 'log-line';
    if (l.includes('信号') || l.includes('配对')) cls += ' signal-line';
    else if (l.includes('异常') || l.includes('错误') || l.includes('⚠️')) cls += ' error-line';
    else if (l.includes('跳过') || l.includes('非交易')) cls += ' warn-line';
    return `<div class="${cls}">${l}</div>`;
  }).join('');
  box.scrollTop = box.scrollHeight;
}

// ═══════════════════════════════════════
// 主循环
// ═══════════════════════════════════════
async function refresh() {
  const [sysStatus, heartbeat, snapshot, signals, logText] = await Promise.all([
    fetchJSON('/api/status'),
    fetchJSON('/api/heartbeat'),
    fetchJSON('/api/snapshot'),
    fetchJSON('/api/signals'),
    fetchText('/api/logs'),
  ]);

  renderStatusBar(sysStatus || {isRunning: false}, heartbeat);
  renderTimeline(heartbeat, signals);
  renderStocks(snapshot, signals);
  renderStats(signals);
  renderLogs(logText);

  const now = new Date();
  document.getElementById('refreshInfo').textContent =
    `最后刷新：${now.toLocaleTimeString('zh-CN')} | 每${REFRESH_INTERVAL/1000}秒自动刷新`;
}

refresh();
setInterval(refresh, REFRESH_INTERVAL);
</script>
</body>
</html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    """自定义HTTP请求处理器，提供API和仪表盘页面"""

    def do_GET(self):
        if self.path == '/' or self.path == '/dashboard':
            self.serve_dashboard()
        elif self.path == '/api/status':
            self.serve_json(get_system_status())
        elif self.path == '/api/heartbeat':
            self.serve_json(safe_read_json(HEARTBEAT_FILE))
        elif self.path == '/api/snapshot':
            self.serve_json(safe_read_json(SNAPSHOT_FILE))
        elif self.path == '/api/signals':
            self.serve_json(safe_read_json(SIGNALS_FILE))
        elif self.path == '/api/logs':
            self.serve_text('\n'.join(get_recent_logs(50)))
        else:
            self.send_error(404)

    def serve_dashboard(self):
        data = DASHBOARD_HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def serve_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(data))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def serve_text(self, text):
        data = text.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', len(data))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        """静默日志"""
        pass


def main():
    parser = argparse.ArgumentParser(description="T+0 盯盘仪表盘服务器")
    parser.add_argument("--port", type=int, default=8899, help="端口号（默认8899）")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    server = HTTPServer(('127.0.0.1', args.port), DashboardHandler)
    url = f"http://localhost:{args.port}"

    print(f"📊 T+0 盯盘仪表盘已启动: {url}")
    print(f"   按 Ctrl+C 退出")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n仪表盘已关闭")
        server.server_close()


if __name__ == "__main__":
    main()
