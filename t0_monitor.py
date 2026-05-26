#!/usr/bin/env python3
"""
T+0 日内盯盘脚本 - 5分钟高频版
功能：交易时段每5分钟检查15只股票，输出T+0配对信号
用法：python t0_monitor.py [--once] [--interval 300]
  --once     只执行一次检查
  --interval 检查间隔秒数（默认300=5分钟）
"""

import json
import os
import subprocess
import sys
import time
import argparse
from datetime import datetime, date, timedelta

# ═══════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════
CLI_PATH = r"C:\Users\Ryan\.workbuddy\plugins\marketplaces\cb_teams_marketplace\plugins\finance-data\skills\westock-data\scripts\index.js"

# 数据目录：默认放在脚本同级data/目录，也可通过 --data-dir 参数覆盖
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.path.join(_SCRIPT_DIR, "data")
SIGNALS_DIR = DEFAULT_DATA_DIR
SIGNALS_FILE = os.path.join(SIGNALS_DIR, "t0-signals-today.json")
LOG_FILE = os.path.join(SIGNALS_DIR, "t0-monitor.log")
PID_FILE = os.path.join(SIGNALS_DIR, "t0-monitor.pid")
HOLIDAYS_FILE = os.path.join(SIGNALS_DIR, "holidays.txt")
HEARTBEAT_FILE = os.path.join(SIGNALS_DIR, "t0-heartbeat.json")
SNAPSHOT_FILE = os.path.join(SIGNALS_DIR, "t0-snapshot.json")
HISTORY_DIR = os.path.join(SIGNALS_DIR, "history")

# 交易时段
TRADING_SESSIONS = [
    (9, 30, 11, 30),   # 上午盘
    (13, 0, 15, 0),     # 下午盘
]

# 标的分组
GROUP_A = ["sz002594", "sz300750", "sh688041", "sz300308", "sz300502", "sh688025", "sz002222", "sz002156"]
GROUP_B = ["sh688503", "sh688062", "sz300660", "sh688778", "sz300450", "sh601208", "sz300014"]
ALL_CODES = GROUP_A + GROUP_B

STOCK_NAMES = {
    "sz002594": "比亚迪", "sz300750": "宁德时代", "sh688041": "海光信息",
    "sz300308": "中际旭创", "sz300502": "新易盛", "sh688025": "杰普特",
    "sz002222": "福晶科技", "sz002156": "通富微电", "sh688503": "聚和材料",
    "sh688062": "迈威生物", "sz300660": "江苏雷利", "sh688778": "厦钨新能",
    "sz300450": "先导智能", "sh601208": "东材科技", "sz300014": "亿纬锂能"
}

# T+0禁用标的（波动太小不适合做T，仅监控行情不触发信号）
T0_DISABLED = {"sz002594"}  # 比亚迪：振幅小，低吸信号容易接飞刀

# 交易成本
COMMISSION_RATE = 0.0001    # 万一 买卖双边
STAMP_TAX_RATE = 0.0005     # 万五 卖出单边
ROUND_TRIP_COST = COMMISSION_RATE * 2 + STAMP_TAX_RATE  # 0.07%
MIN_PROFIT_TARGET = 0.006   # 0.6% 净收益目标
MIN_SPREAD = MIN_PROFIT_TARGET + ROUND_TRIP_COST  # 0.67% 最小差价

# ═══════════════════════════════════════════════════
# 日内强制闭环配置
# ═══════════════════════════════════════════════════
# 三个时段的信号门槛
PHASE_NORMAL_END      = (13, 30)   # 09:30-13:30 精选模式：条件≥2
PHASE_ACTIVE_END      = (14, 30)   # 13:30-14:30 主动寻配：条件≥1 + 优先配对未平仓
PHASE_FORCECLOSE_END  = (14, 50)   # 14:30-14:50 强制收尾：无条件配对
# 14:50 硬截止：所有未配对仓位按市价强制闭环

# 主力净流入/流出"收窄"判断阈值
# 改为：净流入绝对值 < 500万 **且** 相比上一期（如有）方向性改善才算收窄
MAIN_FLOW_NARROW_THRESHOLD = 5_000_000  # 500万

# ═══════════════════════════════════════════════════
# 新一代策略配置（VWAP锚定 + 多信号共振）
# ═══════════════════════════════════════════════════

# —— 趋势过滤 ——
EMA_FAST = 20          # 快线周期（日线MA20替代EMA20，下同）
EMA_SLOW = 60          # 慢线周期
TREND_LOOKBACK = 60    # 趋势回溯天数

# —— VWAP锚定 ——
VWAP_DEVIATION_THRESHOLD = 2.0  # 价格偏离VWAP超过此%视为远离锚点（均值回归机会）

# —— ORB开盘区间 ——
ORB_START = (9, 30)    # 开盘区间起始
ORB_END = (9, 45)      # 开盘区间结束（前15分钟）

# —— 入场信号确认 ——
CONFIRM_MIN_TOTAL = 3   # 至少满足3个确认条件（含A+B）
SIGNAL_COOLDOWN_MINUTES = 20      # 同股两次信号最小间隔（分钟）
SIGNAL_MIN_PRICE_MOVE = 1.5       # 同股两次信号最小价格变动（%）
FORCE_CLOSE_COOLDOWN = False      # 强制闭环不受冷却限制

# —— 风控参数 ——
MAX_POSITION_RATIO = 0.25    # 单笔T仓不超过底仓的25%
MAX_CONCURRENT_POSITIONS = 2  # 最多同时持有未配对T仓的股票数
HARD_STOP_LOSS = -1.5         # 硬止损：入场价-1.5%
TIME_STOP_MINUTES = 30        # 时间止损：开仓30分钟未盈利即平仓
CONSECUTIVE_LOSS_FUSE = 3     # 连续亏损3笔后当日停止开新仓

# ═══════════════════════════════════════════════════
# 通知配置
# ═══════════════════════════════════════════════════
NOTIFICATION_SOUND = True       # 声音提醒（Windows内置，零依赖）
NOTIFICATION_TOAST = True       # Windows桌面弹窗通知
PUSHPLUS_TOKEN = ""             # PushPlus微信推送token（https://www.pushplus.plus/ 注册获取，留空=不推送）
SERVERCHAN_KEY = ""             # Server酱SendKey（https://sct.ftqq.com/ 注册获取，留空=不推送）

# 报告目录
REPORTS_DIR = os.path.join(DEFAULT_DATA_DIR, "reports")

# ═══════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════

def write_pid():
    """写入当前进程PID到文件"""
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    log(f"PID已记录: {os.getpid()}")

def remove_pid():
    """清理PID文件"""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass

def check_already_running():
    """检查是否已有实例在运行，返回True表示已有实例"""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            old_pid = f.read().strip()
        if not old_pid:
            return False
        # 检查进程是否存在且是python进程
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {old_pid}", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        if old_pid in result.stdout:
            return True
        else:
            log(f"旧进程PID:{old_pid}已不存在，清理PID文件")
            os.remove(PID_FILE)
            return False
    except Exception as e:
        log(f"检查进程异常: {e}")
        return False

def load_holidays():
    """加载节假日列表（每行一个日期 YYYY-MM-DD）"""
    holidays = set()
    if os.path.exists(HOLIDAYS_FILE):
        try:
            with open(HOLIDAYS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        holidays.add(line)
        except Exception:
            pass
    return holidays

def is_trading_day():
    """判断今天是否是交易日（周一至周五且非节假日）"""
    today = datetime.now()
    # 周末排除
    if today.weekday() >= 5:
        return False
    # 节假日排除
    holidays = load_holidays()
    today_str = today.strftime("%Y-%m-%d")
    if today_str in holidays:
        return False
    return True

def log(msg):
    """同时输出到控制台和日志文件"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except:
        pass

def is_trading_hours():
    """判断当前是否在交易时段"""
    now = datetime.now()
    for sh, sm, eh, em in TRADING_SESSIONS:
        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        if start <= now <= end:
            return True
    return False

def get_trading_phase():
    """判断当前处于哪个交易阶段，返回阶段名称和信号门槛
    
    阶段划分：
    - "normal":    09:30-13:30 精选模式，条件≥2
    - "active":    13:30-14:30 主动寻配，条件≥1 + 优先配对未平仓
    - "forceclose":14:30-14:50 强制收尾，无条件配对
    - "hardclose": 14:50之后   硬截止，所有未配对仓位按市价强制闭环
    - "closed":    15:00之后   收盘
    """
    now = datetime.now()
    h, m = now.hour, now.minute
    
    # 收盘后
    if h >= 15:
        return "closed", 0
    
    # 硬截止（14:50-15:00）
    if h == 14 and m >= 50:
        return "hardclose", 0
    
    # 强制收尾（14:30-14:50）
    if h == 14 and m >= 30:
        return "forceclose", 0
    
    # 主动寻配（13:30-14:30）
    phase_active_end_h, phase_active_end_m = PHASE_ACTIVE_END
    if (h > 13 or (h == 13 and m >= 30)) and (h < phase_active_end_h or (h == phase_active_end_h and m < phase_active_end_m)):
        return "active", 1
    
    # 精选模式（交易时段内其余时间）
    if is_trading_hours():
        return "normal", 2
    
    return "closed", 0

# ═══════════════════════════════════════════════════
# 通知系统
# ═══════════════════════════════════════════════════

def notify_signal(signal_type, stock_name, price, details_str, pair_msg=""):
    """信号触发时发送通知：声音 + 桌面弹窗 + 微信推送"""
    direction = "🟢低吸" if signal_type == "low" else "🔴高抛"
    title = f"T+0 {direction}: {stock_name}"
    body = f"{stock_name} 现价{price}\n{details_str}"
    if pair_msg:
        body += f"\n{pair_msg}"

    # 1) 声音提醒
    if NOTIFICATION_SOUND:
        try:
            import winsound
            if signal_type == "low":
                # 低吸：上升音调（低→高）
                winsound.Beep(600, 200)
                winsound.Beep(900, 200)
                winsound.Beep(1200, 300)
            else:
                # 高抛：下降音调（高→低）
                winsound.Beep(1200, 200)
                winsound.Beep(900, 200)
                winsound.Beep(600, 300)
        except Exception:
            pass

    # 2) Windows桌面弹窗
    if NOTIFICATION_TOAST:
        try:
            _show_windows_toast(title, body)
        except Exception:
            pass

    # 3) PushPlus微信推送
    if PUSHPLUS_TOKEN:
        try:
            _pushplus_send(title, body)
        except Exception:
            pass

    # 4) Server酱推送
    if SERVERCHAN_KEY:
        try:
            _serverchan_send(title, body)
        except Exception:
            pass

def _show_windows_toast(title, body):
    """Windows 10/11 桌面弹窗通知（PowerShell方式，零依赖）"""
    # 转义PowerShell特殊字符
    safe_title = title.replace("'", "''").replace('"', '`"')
    safe_body = body.replace("'", "''").replace('"', '`"').replace("\n", "&#10;")
    ps_script = f"""
[void] [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
$objNotify = New-Object System.Windows.Forms.NotifyIcon
$objNotify.Icon = [System.Drawing.SystemIcons]::Information
$objNotify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
$objNotify.BalloonTipTitle = '{safe_title}'
$objNotify.BalloonTipText = '{safe_body}'
$objNotify.Visible = $true
$objNotify.ShowBalloonTip(8000)
Start-Sleep -Seconds 10
$objNotify.Dispose()
"""
    subprocess.Popen(
        ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
        creationflags=0x08000000,  # CREATE_NO_WINDOW
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def _pushplus_send(title, content):
    """PushPlus微信推送"""
    import urllib.request
    import urllib.parse
    url = f"http://www.pushplus.plus/send?token={PUSHPLUS_TOKEN}&title={urllib.parse.quote(title)}&content={urllib.parse.quote(content)}&template=html"
    urllib.request.urlopen(url, timeout=10)

def _serverchan_send(title, content):
    """Server酱推送"""
    import urllib.request
    import urllib.parse
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send?title={urllib.parse.quote(title)}&desp={urllib.parse.quote(content)}"
    urllib.request.urlopen(url, timeout=10)

def notify_daily_report(report_path):
    """收盘日报生成通知"""
    title = f"T+0盯盘日报 | {today_str()}"
    body = f"日报已生成，请在浏览器查看"
    if NOTIFICATION_SOUND:
        try:
            import winsound
            for _ in range(3):
                winsound.Beep(800, 150)
                winsound.Beep(1000, 150)
        except Exception:
            pass
    if NOTIFICATION_TOAST:
        try:
            _show_windows_toast(title, body)
        except Exception:
            pass

def now_cst():
    """当前北京时间字符串"""
    return datetime.now().strftime("%H:%M")

def today_str():
    """今天日期字符串"""
    return datetime.now().strftime("%Y-%m-%d")

def parse_markdown_table(text):
    """解析CLI输出的Markdown表格，返回字典列表"""
    if not text or not text.strip():
        return []
    
    lines = text.strip().split("\n")
    # 找表头行和分隔行
    header_line = None
    data_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and "---" in stripped:
            continue  # 分隔行跳过
        if stripped.startswith("|"):
            if header_line is None:
                header_line = stripped
            else:
                data_lines.append(stripped)
    
    if not header_line or not data_lines:
        # 可能是单股非表格输出，尝试解析
        return []
    
    # 解析表头
    headers = [h.strip().lower().replace(" ", "_") for h in header_line.split("|") if h.strip()]
    
    # 解析数据行
    results = []
    for line in data_lines:
        cells = [c.strip() for c in line.split("|") if c.strip() or True]
        # 重新分割以保留空单元格
        cells = line.split("|")
        cells = [c.strip() for c in cells]
        # 去掉首尾空元素
        while cells and cells[0] == "":
            cells.pop(0)
        while cells and cells[-1] == "":
            cells.pop()
        
        if len(cells) >= len(headers):
            row = {}
            for i, h in enumerate(headers):
                row[h] = cells[i] if i < len(cells) else ""
            results.append(row)
    
    return results

def run_cli(args):
    """执行 westock-data CLI 命令，返回解析后的字典列表"""
    cmd = ["node", CLI_PATH] + args
    cmd_desc = " ".join(args[:3])  # 日志用简短描述
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        # 防御性检查：Windows后台进程模式下stdout/stderr可能为None
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if result.returncode == 0 and stdout.strip():
            parsed = parse_markdown_table(stdout)
            if parsed:
                return parsed
            # 表格解析失败，记录原始输出前100字符用于排查
            log(f"  CLI解析失败({cmd_desc}): {stdout.strip()[:100]}")
            return None
        else:
            if stderr.strip():
                log(f"  CLI错误({cmd_desc}): {stderr.strip()[:150]}")
            elif result.returncode != 0:
                log(f"  CLI退出码({cmd_desc}): {result.returncode}")
            return None
    except subprocess.TimeoutExpired:
        log(f"  CLI超时: {cmd_desc}")
        return None
    except FileNotFoundError:
        log(f"  CLI未找到: node命令不可用，请检查PATH")
        return None
    except Exception as e:
        log(f"  CLI异常({cmd_desc}): {type(e).__name__}: {e}")
        return None

# ═══════════════════════════════════════════════════
# 数据拉取
# ═══════════════════════════════════════════════════

def fetch_all_data():
    """并行拉取行情、技术指标、资金流向"""
    a_codes = ",".join(GROUP_A)
    b_codes = ",".join(GROUP_B)

    log("拉取数据中...")

    # 行情
    quote_a = run_cli(["quote", a_codes])
    quote_b = run_cli(["quote", b_codes])

    # 技术指标
    tech_a = run_cli(["technical", a_codes, "--group", "macd,rsi,ma"])
    tech_b = run_cli(["technical", b_codes, "--group", "macd,rsi,ma"])

    # 资金流向
    fund_a = run_cli(["asfund", a_codes])
    fund_b = run_cli(["asfund", b_codes])

    # 合并数据 - 返回的是字典列表，按code建索引
    quotes = {}
    for data_list in [quote_a, quote_b]:
        if data_list and isinstance(data_list, list):
            for item in data_list:
                code = item.get("code", item.get("symbol", ""))
                if code:
                    quotes[code] = item

    techs = {}
    for data_list in [tech_a, tech_b]:
        if data_list and isinstance(data_list, list):
            for item in data_list:
                code = item.get("code", item.get("symbol", ""))
                if code:
                    techs[code] = item

    funds = {}
    for data_list in [fund_a, fund_b]:
        if data_list and isinstance(data_list, list):
            for item in data_list:
                code = item.get("code", item.get("symbol", ""))
                if code:
                    funds[code] = item

    log(f"数据拉取完成: 行情{len(quotes)}只, 技术{len(techs)}只, 资金{len(funds)}只")
    
    # ====== 回退机制：quote失败时用minute数据补价格 ======
    if len(quotes) == 0:
        log("⚠️ 实时行情接口异常，启用分时数据回退...")
        for code in ALL_CODES:
            minute_data = run_cli(["minute", code])
            if minute_data and isinstance(minute_data, list) and len(minute_data) > 0:
                # 取最后一根分钟线作为当前价
                last_bar = minute_data[-1]
                try:
                    current_price = float(last_bar.get("price", 0))
                except (ValueError, TypeError):
                    continue
                
                # 从所有分钟线提取高低
                prices = []
                for bar in minute_data:
                    try:
                        p = float(bar.get("price", 0))
                        if p > 0:
                            prices.append(p)
                    except (ValueError, TypeError):
                        pass
                
                if prices:
                    day_high = max(prices)
                    day_low = min(prices)
                    # 用kline获取昨日收盘价算涨跌幅
                    prev_close = None
                    kline_data = run_cli(["kline", code, "--freq", "day", "--count", "2"])
                    if kline_data and isinstance(kline_data, list) and len(kline_data) >= 2:
                        try:
                            prev_close = float(kline_data[-2].get("last", kline_data[-2].get("close", 0)))
                        except (ValueError, TypeError):
                            pass
                    
                    change_pct = 0
                    if prev_close and prev_close > 0:
                        change_pct = (current_price - prev_close) / prev_close * 100
                    
                    quotes[code] = {
                        "code": code,
                        "price": current_price,
                        "high": day_high,
                        "low": day_low,
                        "changePercent": round(change_pct, 2),
                        "change_pct": round(change_pct, 2),
                        "volume_ratio": 1.0,  # 分时数据不含量比，给中性值
                        "turnover_rate": 0,
                    }
        log(f"  分时回退完成: 行情{len(quotes)}只")
    
    return quotes, techs, funds

# ═══════════════════════════════════════════════════
# 新一代策略引擎：VWAP锚定 + 多信号共振 + 风控
# ═══════════════════════════════════════════════════

# 全局状态（跨检查周期保留）
_strategy_state = {
    "trendCache": {},      # {code: {"trend": "BULL"|"BEAR"|"RANGE", "ma20": float, "ma60": float, "updated": timestamp}}
    "orbCache": {},        # {code: {"orbHigh": float, "orbLow": float}}
    "coolingUntil": {},    # {code: "HH:MM"} 冷却期截止时间
    "consecutiveLosses": 0,  # 全局连续亏损计数
    "fuseBlown": False,      # 熔断状态
}


def _time_to_minutes(time_str):
    """将HH:MM转为分钟数"""
    try:
        h, m = map(int, time_str.split(":"))
        return h * 60 + m
    except Exception:
        return 0


def fetch_minute_data(code):
    """获取单只股票的日内分时数据（用于VWAP计算）"""
    return run_cli(["minute", code])


def fetch_trend_data(code):
    """获取单只股票的日线数据（用于趋势判断）"""
    klines = run_cli(["kline", code, "--freq", "day", "--count", str(TREND_LOOKBACK)])
    tech_ma = run_cli(["technical", code, "--group", "ma"])
    
    result = {"klines": klines or [], "ma20": None, "ma60": None}
    
    if tech_ma:
        t = tech_ma[0] if tech_ma else {}
        for key, val in t.items():
            if "ma_20" in key.lower() and val and val != "-":
                try:
                    result["ma20"] = float(val)
                except (ValueError, TypeError):
                    pass
            elif "ma_60" in key.lower() and val and val != "-":
                try:
                    result["ma60"] = float(val)
                except (ValueError, TypeError):
                    pass
    return result


def classify_trend(ma20, ma60, price):
    """根据均线排列判断趋势
    
    Returns:
        "BULL":  多头排列（MA20 > MA60，价格在两者上方）
        "BEAR":  空头排列（MA20 < MA60，价格在两者下方）
        "RANGE": 震荡（均线缠绕，无明显排列）
    """
    if ma20 is None or ma60 is None or price is None:
        return "RANGE"
    
    diff_pct = abs(ma20 - ma60) / ma60 * 100
    
    if diff_pct < 1.5:
        # 均线缠绕（差距<1.5%），震荡市
        return "RANGE"
    
    if ma20 > ma60:
        # 多头排列：MA20在MA60上方
        if price > ma20:
            return "BULL"   # 标准多头
        elif price > ma60:
            return "BULL"   # 回调但仍在慢线上方，偏多
        else:
            return "RANGE"  # 跌穿双线，转入震荡
    else:
        # 空头排列：MA20在MA60下方
        if price < ma20:
            return "BEAR"   # 标准空头
        elif price < ma60:
            return "BEAR"   # 反弹但仍在慢线下方，偏空
        else:
            return "RANGE"  # 突破双线，转入震荡


def calc_vwap(minute_bars):
    """从分时数据计算日内VWAP（成交量加权均价）
    
    VWAP = Σ(价格 × 成交量) / Σ(成交量)
    从开盘累计到当前时刻
    """
    if not minute_bars:
        return None
    
    total_pv = 0.0   # 价量乘积总和
    total_vol = 0    # 成交量总和
    
    for bar in minute_bars:
        try:
            price = float(bar.get("price", 0))
            volume = float(bar.get("volume", 0))
        except (ValueError, TypeError):
            continue
        if price > 0 and volume > 0:
            total_pv += price * volume
            total_vol += volume
    
    if total_vol == 0:
        return None
    
    vwap = total_pv / total_vol
    return round(vwap, 2)


def get_orb(code):
    """获取开盘区间（ORB: Opening Range Breakout）
    记录09:30-09:45之间的最高价和最低价作为日内关键参考位
    """
    global _strategy_state
    
    now = datetime.now()
    h, m = now.hour, now.minute
    
    # 09:30-09:45：收集ORB数据
    bars = fetch_minute_data(code)
    if not bars:
        return _strategy_state["orbCache"].get(code, {})
    
    orb_high = None
    orb_low = None
    for bar in bars:
        bar_time = str(bar.get("time", "")).strip()
        try:
            bar_minutes = int(bar_time[:2]) * 60 + int(bar_time[2:])
        except (ValueError, IndexError):
            continue
        # 只取09:30-09:45的数据
        if 570 <= bar_minutes <= 585:  # 9*60+30=570, 9*60+45=585
            try:
                p = float(bar.get("price", 0))
            except (ValueError, TypeError):
                continue
            if p > 0:
                if orb_high is None or p > orb_high:
                    orb_high = p
                if orb_low is None or p < orb_low:
                    orb_low = p
    
    if orb_high and orb_low:
        _strategy_state["orbCache"][code] = {"orbHigh": orb_high, "orbLow": orb_low}
    
    return _strategy_state["orbCache"].get(code, {})


def check_entry_positive(code, quote, vwap, trend, orb):
    """检查正T（先买后卖）入场信号 - 多信号共振确认
    
    必须满足 A(锚点) + B(量价) + 至少1个辅助条件(C~F)
    
    Returns:
        (confirmed, strength, details, entry_zone, stop_loss, target_zone)
    """
    confirmed = []
    
    # 提取行情数据
    try:
        price = float(quote.get("price", 0))
        high = float(quote.get("high", 0))
        low = float(quote.get("low", 0))
        change_pct = float(quote.get("changePercent", quote.get("change_pct", 0)))
    except (ValueError, TypeError):
        return False, 0, [], None, None, None
    
    if price <= 0:
        return False, 0, [], None, None, None
    
    # ═══ A: VWAP锚点 — 价格在VWAP附近或下方 ═══
    if vwap and price > 0:
        vwap_dev = (price - vwap) / vwap * 100
        if vwap_dev < 0.5:
            confirmed.append(f"A锚点:VWAP支撑(偏差{vwap_dev:+.2f}%)")
    
    # ═══ B: 量价配合 — 缩量止跌 + 放量反弹 ═══
    volume_ratio = None
    for key in ["volume_ratio", "volumne_ratio"]:
        val = quote.get(key)
        if val and val != "-":
            try:
                volume_ratio = float(val)
                break
            except (ValueError, TypeError):
                pass
    
    if volume_ratio is not None:
        if change_pct < 0 and volume_ratio < 0.8:
            confirmed.append("B量价:缩量下跌(抛压小)")
        elif change_pct > 0 and volume_ratio > 1.0:
            confirmed.append("B量价:放量反弹(动能足)")
        elif 0.8 <= volume_ratio <= 1.2 and abs(change_pct) < 0.5:
            confirmed.append("B量价:平稳")
    
    # ═══ C: 趋势一致 ═══
    if trend in ("BULL", "RANGE"):
        confirmed.append(f"C趋势:{trend}(允正T)")
    
    # ═══ D: 动量背离 — 价格新低但RSI不新低 ═══
    dist_to_low = (price - low) / low * 100 if low > 0 else 100
    if dist_to_low < 0.5:
        if change_pct > -1.5:
            confirmed.append("D背离:价近低+跌幅收窄")
    
    # ═══ E: 关键位支撑 ═══
    if orb and orb.get("orbLow"):
        orb_low = orb["orbLow"]
        dist_orb = (price - orb_low) / orb_low * 100
        if 0 < dist_orb < 1.5:
            confirmed.append(f"E关键:ORB支撑(距{dist_orb:.1f}%)")
    
    # ═══ F: 时间过滤 ═══
    now = datetime.now()
    h, m = now.hour, now.minute
    if not (h == 9 and m < 45) and not (h == 11 and m >= 15) and not (h == 12):
        confirmed.append("F时间:窗口OK")
    
    # 计算信号强度
    strength = len(confirmed)
    has_core = any("A锚点" in c or "B量价" in c for c in confirmed)
    
    if strength >= CONFIRM_MIN_TOTAL and has_core:
        # 计算入场区间、止损、目标
        entry_zone = f"{round(low * 1.002, 2)}-{round(price, 2)}"
        stop_loss = round(price * (1 + HARD_STOP_LOSS / 100), 2)
        target_zone = f"{round(vwap * 1.01, 2)}-{round(high, 2)}" if vwap else f"{round(price * 1.015, 2)}-{round(high, 2)}"
        return True, strength, confirmed, entry_zone, stop_loss, target_zone
    
    return False, strength, confirmed, None, None, None


def check_entry_negative(code, quote, vwap, trend, orb):
    """检查反T（先卖后买）入场信号 - 多信号共振确认"""
    confirmed = []
    
    try:
        price = float(quote.get("price", 0))
        high = float(quote.get("high", 0))
        low = float(quote.get("low", 0))
        change_pct = float(quote.get("changePercent", quote.get("change_pct", 0)))
    except (ValueError, TypeError):
        return False, 0, [], None, None, None
    
    if price <= 0:
        return False, 0, [], None, None, None
    
    # ═══ A: VWAP锚点 — 价格在VWAP附近或上方 ═══
    if vwap and price > 0:
        vwap_dev = (price - vwap) / vwap * 100
        if vwap_dev > -0.5:
            confirmed.append(f"A锚点:VWAP压力(偏差{vwap_dev:+.2f}%)")
    
    # ═══ B: 量价配合 — 放量滞涨 + 缩量回落 ═══
    volume_ratio = None
    for key in ["volume_ratio", "volumne_ratio"]:
        val = quote.get(key)
        if val and val != "-":
            try:
                volume_ratio = float(val)
                break
            except (ValueError, TypeError):
                pass
    
    if volume_ratio is not None:
        if change_pct > 0 and volume_ratio > 1.5:
            confirmed.append("B量价:放量滞涨(抛压现)")
        elif change_pct < 0 and volume_ratio < 0.8:
            confirmed.append("B量价:缩量回落(卖压减)")
    
    # ═══ C: 趋势一致 ═══
    if trend in ("BEAR", "RANGE"):
        confirmed.append(f"C趋势:{trend}(允反T)")
    
    # ═══ D: 动量背离 — 价格新高但RSI不新高 ═══
    dist_to_high = (high - price) / high * 100 if high > 0 else 100
    if dist_to_high < 0.5:
        if change_pct < 1.5:
            confirmed.append("D背离:价近高+涨幅收窄")
    
    # ═══ E: 关键位压力 ═══
    if orb and orb.get("orbHigh"):
        orb_high = orb["orbHigh"]
        dist_orb = (orb_high - price) / orb_high * 100
        if 0 < dist_orb < 1.5:
            confirmed.append(f"E关键:ORB压力(距{dist_orb:.1f}%)")
    
    # ═══ F: 时间过滤 ═══
    now = datetime.now()
    h, m = now.hour, now.minute
    if not (h == 9 and m < 45) and not (h == 11 and m >= 15) and not (h == 12):
        confirmed.append("F时间:窗口OK")
    
    strength = len(confirmed)
    has_core = any("A锚点" in c or "B量价" in c for c in confirmed)
    
    if strength >= CONFIRM_MIN_TOTAL and has_core:
        entry_zone = f"{round(price, 2)}-{round(high * 0.998, 2)}"
        stop_loss = round(price * (1 - HARD_STOP_LOSS / 100), 2)
        target_zone = f"{round(low, 2)}-{round(vwap * 0.99, 2)}" if vwap else f"{round(low, 2)}-{round(price * 0.985, 2)}"
        return True, strength, confirmed, entry_zone, stop_loss, target_zone
    
    return False, strength, confirmed, None, None, None


def format_signal_card(code, name, direction, price, trend, vwap, strength, details, entry_zone, stop_loss, target_zone):
    """格式化交易信号卡片"""
    trend_emoji = {"BULL": "🟢", "BEAR": "🔴", "RANGE": "🟡"}
    trend_names = {"BULL": "多头", "BEAR": "空头", "RANGE": "震荡"}
    stars = "★" * strength + "☆" * (6 - strength)
    
    vwap_str = f"VWAP={vwap}" if vwap else "VWAP=计算中"
    dev_str = ""
    if vwap and price:
        dev = (price - vwap) / vwap * 100
        dev_str = f" 偏差{dev:+.2f}%"
    
    direction_emoji = "🟢" if direction == "positive" else "🔴"
    direction_name = "正T (先买后卖)" if direction == "positive" else "反T (先卖后买)"
    
    details_str = "\n".join(f"  ✅ {d}" for d in details)
    
    # 条件说明
    legend = "A=锚点 B=量价 C=趋势 D=背离 E=关键位 F=时间"
    
    card = f"""
╔══════════════════════════════════════╗
║  ⚠️ T+0 交易提醒 | {now_cst()}            ║
╠══════════════════════════════════════╣
║  {name} ({code})                 ║
║  ──────────────────────────────      ║
║  趋势：{trend_emoji.get(trend, '⚪')} {trend_names.get(trend, '未知')} | {vwap_str}{dev_str}      ║
║  策略：{direction_emoji} {direction_name}               ║
║  ──────────────────────────────      ║
║  当前价：{price}                        ║
║  入场区间：{entry_zone or '--'}                  ║
║  目标区间：{target_zone or '--'}                  ║
║  止损价：{stop_loss or '--'} (-{abs(HARD_STOP_LOSS)}%)               ║
║  仓位建议：底仓{int(MAX_POSITION_RATIO*100)}%                      ║
║  ──────────────────────────────      ║
║  触发条件（{strength}/6）：                   ║
{details_str}                         ║
║  ──────────────────────────────      ║
║  信号强度：{stars} ({strength}/6) ♜ {legend}    ║
║  ──────────────────────────────      ║
║  ⚠️ 人工确认后执行，盈亏自负       ║
╚══════════════════════════════════════╝"""
    return card


def check_signal_cooling(code):
    """检查信号冷却期"""
    global _strategy_state
    cool = _strategy_state["coolingUntil"].get(code)
    if cool:
        cool_min = _time_to_minutes(cool)
        now_min = datetime.now().hour * 60 + datetime.now().minute
        if now_min < cool_min:
            return True  # 还在冷却期
    return False


def update_signal_cooling(code):
    """更新信号冷却期"""
    global _strategy_state
    now = datetime.now()
    cool_until = now.hour * 60 + now.minute + SIGNAL_COOLDOWN_MINUTES
    cool_h = cool_until // 60
    cool_m = cool_until % 60
    _strategy_state["coolingUntil"][code] = f"{cool_h:02d}:{cool_m:02d}"


def check_risk_limits(signals_data):
    """检查风控限制
    
    Returns:
        (allowed: bool, reason: str)
    """
    global _strategy_state
    
    # 熔断检查
    if _strategy_state.get("fuseBlown"):
        return False, "熔断中（连续亏损≥3笔）"
    
    # 最多2笔未配对检查
    pending_count = 0
    for code, state in signals_data.get("stocks", {}).items():
        if state.get("pendingSignal"):
            pending_count += 1
    
    if pending_count >= MAX_CONCURRENT_POSITIONS:
        return False, f"已达最大同时开仓数({MAX_CONCURRENT_POSITIONS}笔)"
    
    return True, "OK"


def process_entry_signal(signals_data, code, direction, price, strength, details, entry_zone, stop_loss, target_zone, vwap, trend):
    """处理新策略入场信号，写入signals_data"""
    name = STOCK_NAMES.get(code, code)
    time_str = now_cst()
    
    # 防止自我配对
    stock_state = signals_data.setdefault("stocks", {}).setdefault(code, {
        "name": name,
        "completedRounds": [],
        "pendingSignal": None,
        "allSignals": [],
    })
    
    pending = stock_state.get("pendingSignal")
    
    if pending:
        existing_type = pending["signalType"]
        
        # 反向信号：配对成功
        if existing_type != direction:
            pair = _create_pair(pending, direction, price, time_str)
            if pair and pair.get("spread", 0) > MIN_SPREAD:
                # 附加入场信号条件到配对记录（供历史分析）
                pair["entryConditions"] = pending.get("details", [])
                pair["entryStrength"] = pending.get("strength", 0)
                pair["entryTrend"] = pending.get("trend", "")
                pair["entryVWAP"] = pending.get("vwap", 0)
                
                stock_state["completedRounds"].append(pair)
                signals_data.setdefault("completedPairs", []).append({
                    "stock": name, "code": code, **pair
                })
                stock_state["pendingSignal"] = None
                
                # 重置该股票冷却期
                _strategy_state["coolingUntil"].pop(code, None)
                
                msg = (
                    f"  [✅ 配对成功] {name}({code})\n"
                    f"    第{pair['round']}轮{pair['type']}: "
                    f"{pair.get('buyTime','')}@{pair.get('buyPrice','')} → {pair.get('sellTime','')}@{pair.get('sellPrice','')}\n"
                    f"    差价：{pair['spread']:+.2f}% | 净收益：{pair['netReturn']:+.2f}%"
                )
                log(f"配对成功: {name} {pair['type']}第{pair['round']}轮 +{pair['netReturn']:.2f}%")
                
                # 亏损检查
                if pair["netReturn"] < 0:
                    _strategy_state["consecutiveLosses"] += 1
                    if _strategy_state["consecutiveLosses"] >= CONSECUTIVE_LOSS_FUSE:
                        _strategy_state["fuseBlown"] = True
                        msg += f"\n  ⚠️ 连续亏损{_strategy_state['consecutiveLosses']}笔，触发熔断！今日停止开新仓"
                else:
                    _strategy_state["consecutiveLosses"] = 0
                
                return msg
        
        # 同向信号：价格更优时提醒
        else:
            if direction == "low" and price < pending["price"]:
                old_price = pending["price"]
                pending["price"] = price
                pending["time"] = time_str
                improvement = (old_price - price) / old_price * 100
                return (
                    f"  [⚠️ 更优低吸价] {name}({code})\n"
                    f"    已有正T第1笔低吸@{old_price} → 现价{price}更低(-{improvement:.2f}%)\n"
                    f"    💡 如已买入，建议调整止损至{price * (1 + HARD_STOP_LOSS/100):.2f}"
                )
            elif direction == "high" and price > pending["price"]:
                old_price = pending["price"]
                pending["price"] = price
                pending["time"] = time_str
                improvement = (price - old_price) / old_price * 100
                return (
                    f"  [⚠️ 更优高抛价] {name}({code})\n"
                    f"    已有反T第1笔高抛@{old_price} → 现价{price}更高(+{improvement:.2f}%)\n"
                    f"    💡 如已卖出，建议调整回补位至{price * (1 - HARD_STOP_LOSS/100):.2f}"
                )
            else:
                return f"  [忽略] {name}({code}) 同向信号价格未优于已有记录"
    
    # 新开仓：写入pending信号
    else:
        round_num = len(stock_state.get("completedRounds", [])) + 1
        t_type = "正T" if direction == "low" else "反T"
        
        signal = {
            "round": round_num,
            "type": t_type,
            "signalType": direction,
            "time": time_str,
            "price": price,
            "entryZone": entry_zone,
            "stopLoss": stop_loss,
            "targetZone": target_zone,
            "strength": strength,
            "details": details,
            "vwap": vwap,
            "trend": trend,
        }
        
        stock_state["pendingSignal"] = signal
        _strategy_state["coolingUntil"][code] = _compute_cooling_until()
        
        card = format_signal_card(
            code, name, 
            "positive" if direction == "low" else "negative",
            price, trend, vwap, strength, details,
            entry_zone, stop_loss, target_zone
        )
        
        log(f"新信号: {name} {t_type}第{round_num}轮 {'低吸' if direction=='low' else '高抛'}@{price} 强度{strength}/6")
        
        return card


def _compute_cooling_until():
    """计算冷却截止时间"""
    now = datetime.now()
    cool_until = now.hour * 60 + now.minute + SIGNAL_COOLDOWN_MINUTES
    return f"{cool_until // 60:02d}:{cool_until % 60:02d}"


def _create_pair(pending, direction, price, time_str):
    """创建配对记录"""
    if pending["signalType"] == "low" and direction == "high":
        # 正T配对：低吸→高抛
        spread = (price - pending["price"]) / pending["price"] * 100
        net = spread - ROUND_TRIP_COST * 100
        return {
            "round": pending["round"],
            "type": "正T",
            "buyTime": pending["time"],
            "buyPrice": pending["price"],
            "sellTime": time_str,
            "sellPrice": price,
            "spread": round(spread, 2),
            "netReturn": round(net, 2),
        }
    elif pending["signalType"] == "high" and direction == "low":
        # 反T配对：高抛→低吸
        spread = (pending["price"] - price) / pending["price"] * 100
        net = spread - ROUND_TRIP_COST * 100
        return {
            "round": pending["round"],
            "type": "反T",
            "sellTime": pending["time"],
            "sellPrice": pending["price"],
            "buyTime": time_str,
            "buyPrice": price,
            "spread": round(spread, 2),
            "netReturn": round(net, 2),
        }
    return None


# ═══════════════════════════════════════════════════
# 信号判断（旧版，保留用于强制闭环时的简化判断）
# ═══════════════════════════════════════════════════

def check_low_signal(quote, tech, fund):
    """检查低吸信号，返回满足的条件数和详情"""
    conditions = 0
    details = []

    # 条件1: RSI6 < 35 且至少有一个确认信号（防止单独RSI超卖就低吸——接飞刀）
    rsi6 = None
    if tech:
        # 字段名格式: rsi.RSI_6
        for key in ["rsi.rsi_6", "rsi_6", "rsi.rsi6"]:
            val = tech.get(key)
            if val and val != "-":
                try:
                    rsi6 = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if rsi6 is not None:
        if rsi6 < 25:
            # RSI极度超卖，单独算一个强条件
            conditions += 1
            details.append(f"RSI6={rsi6:.1f}极度超卖")
        elif rsi6 < 35:
            # RSI超卖，但需要确认（不算独立条件，只做加分项）
            # 如果同时有MACD绿柱缩短或股价接近低点，才算有效
            details.append(f"RSI6={rsi6:.1f}(待确认)")
            # 检查MACD是否同步
            macd_hist_check = None
            if tech:
                for key in ["macd.macd", "macd_hist", "macd.histogram"]:
                    val = tech.get(key)
                    if val and val != "-":
                        try:
                            macd_hist_check = float(val)
                            break
                        except (ValueError, TypeError):
                            pass
            if macd_hist_check is not None and -0.2 < macd_hist_check < 0.1:
                # MACD绿柱缩短或即将翻红，确认RSI超卖有效
                conditions += 1
                details.append(f"RSI6={rsi6:.1f}+MACD确认")
            # 否则RSI超卖单独不算条件，避免接飞刀

    # 条件2: 当日跌幅 > 1.0%
    change_pct = None
    if quote:
        for key in ["change_percent", "changepct", "changeprecent"]:
            val = quote.get(key)
            if val and val != "-":
                try:
                    change_pct = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if change_pct is not None and change_pct < -1.0:
        conditions += 1
        details.append(f"跌{abs(change_pct):.1f}%")

    # 条件3: 股价接近当日低点（距low不到1%）
    price = None
    low = None
    if quote:
        try:
            price = float(quote.get("price", 0))
            low = float(quote.get("low", 0))
        except (ValueError, TypeError):
            pass
    if price and low and price > 0 and low > 0:
        dist_to_low = (price - low) / low * 100
        if dist_to_low < 1.0:
            conditions += 1
            details.append(f"距低点{dist_to_low:.2f}%")

    # 条件4: MACD柱状线绿柱缩短或即将翻红
    macd_hist = None
    if tech:
        # 字段名: macd.MACD
        for key in ["macd.macd", "macd_hist", "macd.histogram"]:
            val = tech.get(key)
            if val and val != "-":
                try:
                    macd_hist = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if macd_hist is not None:
        if -0.1 < macd_hist < 0:
            conditions += 1
            details.append("MACD绿柱缩短")
        elif 0 <= macd_hist < 0.1:
            conditions += 1
            details.append("MACD即将翻红")

    # 条件5: 主力净流出在收窄（收紧条件：不再白送）
    net_amount = None
    if fund:
        for key in ["mainnetflow", "main_net_flow", "netamount"]:
            val = fund.get(key)
            if val and val != "-":
                try:
                    net_amount = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if net_amount is not None:
        # 新逻辑：主力净流入为正才算"收窄"，或者净流出但金额极小（<阈值）且股价在反弹
        # 不再简单认为 abs < 500万就算收窄（太容易触发）
        if net_amount > 0:
            conditions += 1
            details.append("主力净流入")
        elif net_amount < 0 and abs(net_amount) < MAIN_FLOW_NARROW_THRESHOLD and change_pct is not None and change_pct > -0.5:
            # 净流出很小（<500万）且股价跌幅不大（>-0.5%），说明抛压在减弱
            conditions += 1
            details.append(f"主力流出微弱{abs(net_amount)/10000:.0f}万")

    # 条件6: 量比 < 0.8
    volume_ratio = None
    if quote:
        for key in ["volume_ratio", "volumne_ratio"]:
            val = quote.get(key)
            if val and val != "-":
                try:
                    volume_ratio = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if volume_ratio is not None and 0 < volume_ratio < 0.8:
        conditions += 1
        details.append(f"量比{volume_ratio:.2f}")

    return conditions, details

def check_high_signal(quote, tech, fund):
    """检查高抛信号，返回满足的条件数和详情"""
    conditions = 0
    details = []

    # 条件1: RSI6 > 65
    rsi6 = None
    if tech:
        for key in ["rsi.rsi_6", "rsi_6", "rsi.rsi6"]:
            val = tech.get(key)
            if val and val != "-":
                try:
                    rsi6 = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if rsi6 is not None:
        if rsi6 > 65:
            conditions += 1
            details.append(f"RSI6={rsi6:.1f}")

    # 条件2: 当日涨幅 > 1.0%
    change_pct = None
    if quote:
        for key in ["change_percent", "changepct", "changeprecent"]:
            val = quote.get(key)
            if val and val != "-":
                try:
                    change_pct = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if change_pct is not None and change_pct > 1.0:
        conditions += 1
        details.append(f"涨{change_pct:.1f}%")

    # 条件3: 股价接近当日高点（距high不到1%）
    price = None
    high = None
    if quote:
        try:
            price = float(quote.get("price", 0))
            high = float(quote.get("high", 0))
        except (ValueError, TypeError):
            pass
    if price and high and price > 0 and high > 0:
        dist_to_high = (high - price) / high * 100
        if dist_to_high < 1.0:
            conditions += 1
            details.append(f"距高点{dist_to_high:.2f}%")

    # 条件4: MACD柱状线红柱缩短或即将翻绿
    macd_hist = None
    if tech:
        for key in ["macd.macd", "macd_hist", "macd.histogram"]:
            val = tech.get(key)
            if val and val != "-":
                try:
                    macd_hist = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if macd_hist is not None:
        if 0 < macd_hist < 0.1:
            conditions += 1
            details.append("MACD红柱缩短")
        elif -0.1 < macd_hist < 0:
            conditions += 1
            details.append("MACD即将翻绿")

    # 条件5: 主力净流入在收窄（收紧条件）
    net_amount = None
    if fund:
        for key in ["mainnetflow", "main_net_flow", "netamount"]:
            val = fund.get(key)
            if val and val != "-":
                try:
                    net_amount = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if net_amount is not None:
        if net_amount < 0:
            conditions += 1
            details.append("主力净流出")
        elif net_amount > 0 and abs(net_amount) < MAIN_FLOW_NARROW_THRESHOLD and change_pct is not None and change_pct < 0.5:
            # 净流入很小（<500万）且股价涨幅不大（<0.5%），说明买盘在减弱
            conditions += 1
            details.append(f"主力流入微弱{abs(net_amount)/10000:.0f}万")

    # 条件6: 换手率 > 3%
    turnover = None
    if quote:
        for key in ["turnover_rate", "turnoverrate"]:
            val = quote.get(key)
            if val and val != "-":
                try:
                    turnover = float(val)
                    break
                except (ValueError, TypeError):
                    pass
    if turnover is not None and turnover > 3:
        conditions += 1
        details.append(f"换手{turnover:.1f}%")

    return conditions, details

def calc_rating(spread_pct):
    """根据预估差价计算评级"""
    net = spread_pct - ROUND_TRIP_COST * 100
    if net > 1.5:
        return 3, "⭐⭐⭐"
    elif net > 0.6:
        return 2, "⭐⭐"
    else:
        return 1, "⭐"

def calc_targets_low(price, amplitude_pct):
    """低吸信号触发时，计算高抛目标价"""
    min_target = price * (1 + MIN_SPREAD)
    reasonable = price * (1 + max(amplitude_pct, MIN_SPREAD) / 100 * 0.5)
    return {
        "min": round(min_target, 2),
        "reasonable": round(reasonable, 2),
        "min_pct": round((min_target / price - 1) * 100, 2),
        "reasonable_pct": round((reasonable / price - 1) * 100, 2),
    }

def calc_targets_high(price, amplitude_pct):
    """高抛信号触发时，计算低吸回补价"""
    min_target = price * (1 - MIN_SPREAD)
    reasonable = price * (1 - max(amplitude_pct, MIN_SPREAD) / 100 * 0.5)
    return {
        "min": round(min_target, 2),
        "reasonable": round(reasonable, 2),
        "min_pct": round((1 - min_target / price) * 100, 2),
        "reasonable_pct": round((1 - reasonable / price) * 100, 2),
    }

# ═══════════════════════════════════════════════════
# 信号持久化与配对
# ═══════════════════════════════════════════════════

def load_signals():
    """加载今日信号记录"""
    if not os.path.exists(SIGNALS_FILE):
        return None
    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == today_str():
            return data
    except:
        pass
    return None

def save_signals(data):
    """保存信号记录"""
    os.makedirs(SIGNALS_DIR, exist_ok=True)
    with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def init_signals():
    """初始化今日信号，同时归档昨日数据到 history/"""
    _archive_yesterday()
    
    return {
        "date": today_str(),
        "stocks": {},
        "allSignals": [],
        "completedPairs": [],
    }


def _archive_yesterday():
    """将昨日的信号数据归档到 history/YYYY-MM-DD.json"""
    try:
        if not os.path.exists(SIGNALS_FILE):
            return
        
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        old_date = data.get("date", "")
        if not old_date or old_date == today_str():
            return  # 同一天，无需归档
        
        # 确保 history 目录存在
        os.makedirs(HISTORY_DIR, exist_ok=True)
        
        archive_path = os.path.join(HISTORY_DIR, f"{old_date}.json")
        
        # 不重复归档
        if os.path.exists(archive_path):
            return
        
        # 计算摘要信息
        completed = data.get("completedPairs", [])
        total_return = sum(p.get("netReturn", 0) for p in completed)
        winning = sum(1 for p in completed if p.get("netReturn", 0) > 0)
        
        archive_data = {
            **data,
            "_summary": {
                "totalPairs": len(completed),
                "totalReturn": round(total_return, 2),
                "winRate": round(winning / max(len(completed), 1) * 100, 1),
                "forcedClose": sum(1 for p in completed if p.get("forceclose")),
            }
        }
        
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        
        # 更新汇总索引
        _update_history_index(archive_data["_summary"], old_date)
        
        log(f"📦 昨日数据已归档: {archive_path}")
    except Exception as e:
        log(f"⚠️ 归档失败: {e}")


def _update_history_index(daily_summary, date_str):
    """更新历史汇总索引文件"""
    index_path = os.path.join(HISTORY_DIR, "history-summary.json")
    records = []
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            records = []
    
    # 检查是否已存在（避免重复）
    existing = [r for r in records if r.get("date") != date_str]
    existing.append({"date": date_str, **daily_summary})
    existing.sort(key=lambda r: r["date"])
    
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

def get_stock_state(signals_data, code):
    """获取某只股票的当前状态"""
    return signals_data["stocks"].get(code, {
        "name": STOCK_NAMES.get(code, code),
        "completedRounds": [],
        "pendingSignal": None,
    })

def process_signal(signals_data, code, signal_type, price, rating_int, details, amplitude_pct):
    """处理一个信号，尝试配对"""
    stock_state = get_stock_state(signals_data, code)
    name = STOCK_NAMES.get(code, code)
    time_str = now_cst()
    result_msg = ""

    # 记录信号
    current_round = len(stock_state["completedRounds"]) + 1
    t_type = "正T" if signal_type == "low" else "反T"  # 首笔信号决定T类型方向

    signal_record = {
        "time": time_str,
        "stock": name,
        "code": code,
        "type": signal_type,
        "price": price,
        "rating": rating_int,
        "details": ", ".join(details),
        "amplitude": amplitude_pct,
    }
    signals_data["allSignals"].append(signal_record)

    pending = stock_state.get("pendingSignal")

    if pending is None:
        # 没有未配对信号，这是首笔
        if signal_type == "low":
            t_type = "正T"
            targets = calc_targets_low(price, amplitude_pct)
            signal_info = {
                "round": current_round,
                "type": "正T",
                "leg": 1,
                "signalType": "low",
                "time": time_str,
                "price": price,
                "targets": targets,
            }
            result_msg = (
                f"  【🟢 低吸 — 正T第1笔】\n"
                f"  {name}({code}) | 现价 {price} | 振幅 {amplitude_pct:.1f}%\n"
                f"    信号：{', '.join(details)}\n"
                f"    操作类型：正T（先买后卖）| 第{current_round}轮T+0 | 第1笔/共2笔\n"
                f"    评级：{'⭐' * rating_int}\n"
                f"    💡 T+0买入，需反弹>{MIN_SPREAD*100:.2f}%才盈利\n"
                f"    🎯 高抛目标位：最低{targets['min']}(+{targets['min_pct']}%) | 合理{targets['reasonable']}(+{targets['reasonable_pct']}%)\n"
                f"    ⏳ 等待配对：第2笔高抛信号"
            )
            # 发送通知
            notify_signal("low", name, price, ", ".join(details),
                         f"正T第1笔 | 需反弹>{MIN_SPREAD*100:.2f}%")
        else:
            t_type = "反T"
            targets = calc_targets_high(price, amplitude_pct)
            signal_info = {
                "round": current_round,
                "type": "反T",
                "leg": 1,
                "signalType": "high",
                "time": time_str,
                "price": price,
                "targets": targets,
            }
            result_msg = (
                f"  【🔴 高抛 — 反T第1笔】\n"
                f"  {name}({code}) | 现价 {price} | 振幅 {amplitude_pct:.1f}%\n"
                f"    信号：{', '.join(details)}\n"
                f"    操作类型：反T（先卖后买）| 第{current_round}轮T+0 | 第1笔/共2笔\n"
                f"    评级：{'⭐' * rating_int}\n"
                f"    💡 T+0卖出，需回踩>{MIN_SPREAD*100:.2f}%才盈利\n"
                f"    🎯 低吸回补位：最低{targets['min']}(-{targets['min_pct']}%) | 合理{targets['reasonable']}(-{targets['reasonable_pct']}%)\n"
                f"    ⏳ 等待配对：第2笔低吸信号"
            )
            # 发送通知
            notify_signal("high", name, price, ", ".join(details),
                         f"反T第1笔 | 需回踩>{MIN_SPREAD*100:.2f}%")
        stock_state["pendingSignal"] = signal_info

    else:
        # 有未配对的首笔信号，尝试配对
        pending_type = pending["signalType"]
        if (pending_type == "low" and signal_type == "high"):
            # 正T配对：低吸→高抛
            spread = (price - pending["price"]) / pending["price"] * 100
            net_return = spread - ROUND_TRIP_COST * 100
            pair = {
                "round": pending["round"],
                "type": "正T",
                "buyTime": pending["time"],
                "buyPrice": pending["price"],
                "sellTime": time_str,
                "sellPrice": price,
                "spread": round(spread, 2),
                "netReturn": round(net_return, 2),
            }
            stock_state["completedRounds"].append(pair)
            signals_data["completedPairs"].append({
                "stock": name, "code": code, **pair
            })
            stock_state["pendingSignal"] = None

            result_msg = (
                f"  【✅ 正T配对完成】\n"
                f"  {name}({code}): 第{pair['round']}轮正T\n"
                f"    {pending['time']}低吸@{pending['price']} → {time_str}高抛@{price}\n"
                f"    差价：+{spread:.2f}% | 扣费后净收益：+{net_return:.2f}%"
            )
            # 配对完成通知
            notify_signal("high", name, price, f"正T配对完成",
                         f"买@{pending['price']}→卖@{price} 净+{net_return:.2f}%")

        elif (pending_type == "high" and signal_type == "low"):
            # 反T配对：高抛→低吸
            spread = (pending["price"] - price) / pending["price"] * 100
            net_return = spread - ROUND_TRIP_COST * 100
            pair = {
                "round": pending["round"],
                "type": "反T",
                "sellTime": pending["time"],
                "sellPrice": pending["price"],
                "buyTime": time_str,
                "buyPrice": price,
                "spread": round(spread, 2),
                "netReturn": round(net_return, 2),
            }
            stock_state["completedRounds"].append(pair)
            signals_data["completedPairs"].append({
                "stock": name, "code": code, **pair
            })
            stock_state["pendingSignal"] = None

            result_msg = (
                f"  【✅ 反T配对完成】\n"
                f"  {name}({code}): 第{pair['round']}轮反T\n"
                f"    {pending['time']}高抛@{pending['price']} → {time_str}低吸@{price}\n"
                f"    差价：+{spread:.2f}% | 扣费后净收益：+{net_return:.2f}%"
            )
            # 配对完成通知
            notify_signal("low", name, price, f"反T配对完成",
                         f"卖@{pending['price']}→买@{price} 净+{net_return:.2f}%")

        else:
            # 同向信号：不再静默更新价格，而是提醒用户
            if signal_type == "low" and price < pending["price"]:
                old_price = pending["price"]
                pending["price"] = price
                pending["time"] = time_str
                improvement = (old_price - price) / old_price * 100
                result_msg = (
                    f"  [⚠️ 更优低吸价] {name}({code})\n"
                    f"    已有正T第1笔低吸@{old_price} → 现价{price}更低(-{improvement:.2f}%)\n"
                    f"    💡 如已买入，可考虑调整止损至{price * (1 - 0.01):.2f}（-1%）"
                )
            elif signal_type == "high" and price > pending["price"]:
                old_price = pending["price"]
                pending["price"] = price
                pending["time"] = time_str
                improvement = (price - old_price) / old_price * 100
                result_msg = (
                    f"  [⚠️ 更优高抛价] {name}({code})\n"
                    f"    已有反T第1笔高抛@{old_price} → 现价{price}更高(+{improvement:.2f}%)\n"
                    f"    💡 如已卖出，可考虑调整回补位至{price * (1 + 0.01):.2f}（+1%）"
                )
            else:
                result_msg = f"  [忽略] {name}({code}) 同向信号价格未优于已有记录"

    signals_data["stocks"][code] = stock_state
    return result_msg

# ═══════════════════════════════════════════════════
# 主检查逻辑
# ═══════════════════════════════════════════════════

def write_heartbeat(check_count, has_signal, signal_count, quotes_count, error_msg=""):
    """写入心跳文件，供Web仪表盘读取"""
    heartbeat = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pid": os.getpid(),
        "checkCount": check_count,
        "hasSignal": has_signal,
        "signalCount": signal_count,
        "quotesFetched": quotes_count,
        "error": error_msg,
        "interval": 300,
    }
    try:
        os.makedirs(SIGNALS_DIR, exist_ok=True)
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            json.dump(heartbeat, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def write_snapshot(quotes, techs, funds):
    """写入当前行情快照，供Web仪表盘展示"""
    snapshot = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stocks": {}
    }
    for code in ALL_CODES:
        quote = quotes.get(code, {})
        tech = techs.get(code, {})
        fund = funds.get(code, {})
        try:
            price = float(quote.get("price", quote.get("currentPrice", 0)))
            low = float(quote.get("low", quote.get("todayLow", 0)))
            high = float(quote.get("high", quote.get("todayHigh", 0)))
            change_pct = float(quote.get("change_percent", quote.get("changepct", quote.get("changeprecent", 0))))
        except (ValueError, TypeError):
            price = low = high = change_pct = 0

        rsi6 = None
        if tech:
            for key in ["rsi.rsi_6", "rsi_6", "rsi.rsi6"]:
                val = tech.get(key)
                if val and val != "-":
                    try: rsi6 = float(val); break
                    except: pass

        main_net = None
        if fund:
            for key in ["mainnetflow", "main_net_flow", "netamount"]:
                val = fund.get(key)
                if val and val != "-":
                    try: main_net = float(val); break
                    except: pass

        snapshot["stocks"][code] = {
            "name": STOCK_NAMES.get(code, code),
            "price": price,
            "high": high,
            "low": low,
            "changePercent": change_pct,
            "rsi6": rsi6,
            "mainNetFlow": main_net,
        }
    try:
        os.makedirs(SIGNALS_DIR, exist_ok=True)
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _generate_dashboard():
    """生成静态仪表盘HTML + 确保微静态服务器运行（端口8899）"""
    # 启动微静态文件服务器（如未运行）
    _ensure_data_server()
    
    # 生成仪表盘HTML
    try:
        script_path = os.path.join(_SCRIPT_DIR, "generate_dashboard.py")
        if os.path.exists(script_path):
            subprocess.run(
                [sys.executable, script_path],
                capture_output=True, timeout=15
            )
    except Exception:
        pass


def _ensure_data_server():
    """确保 data/ 目录的微静态HTTP服务器在端口8899运行"""
    import socket
    s = socket.socket()
    port_in_use = s.connect_ex(('127.0.0.1', 8899)) == 0
    s.close()
    if port_in_use:
        return  # 已经在运行
    
    # 后台启动 http.server，cwd 指定为 data/ 目录
    subprocess.Popen(
        [sys.executable, '-m', 'http.server', '8899'],
        cwd=DEFAULT_DATA_DIR,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )
    log("  微静态服务器已启动: http://localhost:8899")

def run_check(force=False):
    """执行一次完整的T+0信号检查。force=True时忽略交易时段限制（用于收盘日报）"""
    global _check_count
    if not force and not is_trading_hours():
        log("⏸️ 非交易时段，跳过")
        write_heartbeat(getattr(run_check, '_count', 0), False, 0, 0, "非交易时段")
        _generate_dashboard()
        return

    # 加载/初始化信号数据
    signals_data = load_signals()
    if signals_data is None:
        signals_data = init_signals()

    # 拉取数据
    quotes, techs, funds = fetch_all_data()

    if not quotes:
        log("⚠️ 未获取到行情数据，跳过本次检查")
        write_heartbeat(0, False, 0, 0, "未获取到行情数据")
        _generate_dashboard()
        return

    # 获取当前交易阶段
    phase, min_conditions = get_trading_phase()
    log(f"  当前阶段: {phase} (最低条件数: {min_conditions})")

    output_lines = [f"\n🎯 T+0交易信号 | {now_cst()} | 阶段:{phase} | 策略:VWAP共振"]
    has_signal = False

    # ═══ 阶段0: 获取策略数据（VWAP、趋势、ORB） ═══
    # 批量获取技术面MA数据（一行拉所有）
    all_ma = run_cli(["technical", ",".join(ALL_CODES), "--group", "ma"])
    ma_map = {}
    if all_ma:
        for item in all_ma:
            code = item.get("code", "")
            if code:
                ma_map[code] = item

    # ORB仅在09:45第一次计算
    now = datetime.now()
    if now.hour == 9 and now.minute >= 45 and not _strategy_state["orbCache"]:
        log("  计算ORB开盘区间(09:30-09:45)...")
        for code in ALL_CODES:
            if code in T0_DISABLED:
                continue
            get_orb(code)

    # ═══ 阶段1: 新策略引擎 — VWAP锚定+多信号共振 ═══
    for code in ALL_CODES:
        # T+0禁用标的：只记录行情，不触发信号
        if code in T0_DISABLED:
            continue

        quote = quotes.get(code, {})
        tech = techs.get(code, {})
        fund = funds.get(code, {})

        if not quote:
            continue

        try:
            price = float(quote.get("price", quote.get("currentPrice", 0)))
            low = float(quote.get("low", quote.get("todayLow", 0)))
            high = float(quote.get("high", quote.get("todayHigh", 0)))
            change_pct = float(quote.get("changePercent", quote.get("change_pct", 0)))
        except (ValueError, TypeError):
            continue

        if price <= 0:
            continue

        # 信号冷却检查
        if check_signal_cooling(code):
            continue

        # 风控限制检查
        risk_ok, risk_reason = check_risk_limits(signals_data)
        if not risk_ok:
            if _strategy_state.get("fuseBlown") and not hasattr(run_check, '_fuse_reported'):
                output_lines.append(f"  🛑 风控熔断：{risk_reason}")
                run_check._fuse_reported = True
            continue

        # 获取趋势数据
        ma_data = ma_map.get(code, {})
        ma20 = None
        ma60 = None
        if ma_data:
            for key, val in ma_data.items():
                if "ma_20" in key.lower() and val and val != "-":
                    try:
                        ma20 = float(val)
                    except (ValueError, TypeError):
                        pass
                elif "ma_60" in key.lower() and val and val != "-":
                    try:
                        ma60 = float(val)
                    except (ValueError, TypeError):
                        pass
        
        trend = classify_trend(ma20, ma60, price)

        # 获取VWAP
        minute_bars = fetch_minute_data(code)
        vwap = calc_vwap(minute_bars)

        # ORB
        orb = _strategy_state["orbCache"].get(code, {})

        # 根据趋势确定主策略方向
        if phase in ("normal", "active"):
            # 精选/主动寻配阶段：趋势决定策略偏好
            if trend == "BULL":
                # 多头：只做正T（低吸），禁用反T
                positive_ok, pos_strength, pos_details, pos_entry, pos_stop, pos_target = \
                    check_entry_positive(code, quote, vwap, trend, orb)
                if positive_ok:
                    update_signal_cooling(code)
                    msg = process_entry_signal(signals_data, code, "low", price, pos_strength, 
                                                pos_details, pos_entry, pos_stop, pos_target, vwap, trend)
                    output_lines.append(msg)
                    has_signal = True
            
            elif trend == "BEAR":
                # 空头：只做反T（高抛），禁用正T
                negative_ok, neg_strength, neg_details, neg_entry, neg_stop, neg_target = \
                    check_entry_negative(code, quote, vwap, trend, orb)
                if negative_ok:
                    update_signal_cooling(code)
                    msg = process_entry_signal(signals_data, code, "high", price, neg_strength,
                                                neg_details, neg_entry, neg_stop, neg_target, vwap, trend)
                    output_lines.append(msg)
                    has_signal = True
            
            else:  # RANGE
                # 震荡：正T反T均可，优先检查未配对仓位的反向信号
                stock_state = get_stock_state(signals_data, code)
                pending = stock_state.get("pendingSignal")
                
                if pending:
                    # 有未配对仓位：只检查反向信号
                    if pending["signalType"] == "low":
                        # 已有低吸，等高抛
                        negative_ok, neg_strength, neg_details, neg_entry, neg_stop, neg_target = \
                            check_entry_negative(code, quote, vwap, trend, orb)
                        if negative_ok:
                            update_signal_cooling(code)
                            msg = process_entry_signal(signals_data, code, "high", price, neg_strength,
                                                        neg_details, neg_entry, neg_stop, neg_target, vwap, trend)
                            output_lines.append(msg)
                            has_signal = True
                    else:
                        # 已有高抛，等低吸
                        positive_ok, pos_strength, pos_details, pos_entry, pos_stop, pos_target = \
                            check_entry_positive(code, quote, vwap, trend, orb)
                        if positive_ok:
                            update_signal_cooling(code)
                            msg = process_entry_signal(signals_data, code, "low", price, pos_strength,
                                                        pos_details, pos_entry, pos_stop, pos_target, vwap, trend)
                            output_lines.append(msg)
                            has_signal = True
                else:
                    # 无仓位：两个方向都检查
                    positive_ok, pos_strength, pos_details, pos_entry, pos_stop, pos_target = \
                        check_entry_positive(code, quote, vwap, trend, orb)
                    if positive_ok:
                        update_signal_cooling(code)
                        msg = process_entry_signal(signals_data, code, "low", price, pos_strength,
                                                    pos_details, pos_entry, pos_stop, pos_target, vwap, trend)
                        output_lines.append(msg)
                        has_signal = True
                    
                    if not positive_ok:
                        negative_ok, neg_strength, neg_details, neg_entry, neg_stop, neg_target = \
                            check_entry_negative(code, quote, vwap, trend, orb)
                        if negative_ok:
                            update_signal_cooling(code)
                            msg = process_entry_signal(signals_data, code, "high", price, neg_strength,
                                                        neg_details, neg_entry, neg_stop, neg_target, vwap, trend)
                            output_lines.append(msg)
                            has_signal = True

    # ═══ 阶段1.5: 强制收尾前 — 只配对已有仓位，不准建新仓 ═══
    if phase == "forceclose":
        for code in ALL_CODES:
            if code in T0_DISABLED:
                continue
            quote = quotes.get(code, {})
            if not quote:
                continue
            try:
                price = float(quote.get("price", quote.get("currentPrice", 0)))
            except (ValueError, TypeError):
                continue
            if price <= 0:
                continue
            
            stock_state = get_stock_state(signals_data, code)
            pending = stock_state.get("pendingSignal")
            if not pending:
                continue  # 无未配对仓位，跳过（不准开新仓）
            
            # 获取VWAP和趋势（用于配对判断）
            minute_bars = fetch_minute_data(code)
            vwap = calc_vwap(minute_bars)
            ma_data = ma_map.get(code, {})
            ma20 = ma60 = None
            if ma_data:
                for key, val in ma_data.items():
                    if "ma_20" in key.lower() and val and val != "-":
                        try: ma20 = float(val)
                        except: pass
                    elif "ma_60" in key.lower() and val and val != "-":
                        try: ma60 = float(val)
                        except: pass
            trend = classify_trend(ma20, ma60, price)
            orb = _strategy_state["orbCache"].get(code, {})
            
            # 只检查反向信号（尝试自然配对）
            if pending["signalType"] == "low":
                negative_ok, neg_strength, neg_details, neg_entry, neg_stop, neg_target = \
                    check_entry_negative(code, quote, vwap, trend, orb)
                if negative_ok:
                    msg = process_entry_signal(signals_data, code, "high", price, neg_strength,
                                                neg_details, neg_entry, neg_stop, neg_target, vwap, trend)
                    output_lines.append(msg)
                    has_signal = True
            else:
                positive_ok, pos_strength, pos_details, pos_entry, pos_stop, pos_target = \
                    check_entry_positive(code, quote, vwap, trend, orb)
                if positive_ok:
                    msg = process_entry_signal(signals_data, code, "low", price, pos_strength,
                                                pos_details, pos_entry, pos_stop, pos_target, vwap, trend)
                    output_lines.append(msg)
                    has_signal = True

    # ═══ 阶段2: 强制闭环逻辑（14:30之后） ═══
    if phase in ("forceclose", "hardclose"):
        forceclose_msgs = _force_close_pending(signals_data, quotes, phase)
        if forceclose_msgs:
            output_lines.extend(forceclose_msgs)
            has_signal = True

    # 今日T+0全景
    panorama = ["\n  【📋 今日T+0全景】"]
    
    # 策略状态概览
    trend_count = {"BULL": 0, "BEAR": 0, "RANGE": 0}
    for code in ALL_CODES:
        if code in T0_DISABLED:
            continue
        ma_data = ma_map.get(code, {})
        ma20 = ma60 = None
        if ma_data:
            for key, val in ma_data.items():
                if "ma_20" in key.lower() and val and val != "-":
                    try: ma20 = float(val)
                    except: pass
                elif "ma_60" in key.lower() and val and val != "-":
                    try: ma60 = float(val)
                    except: pass
        quote = quotes.get(code, {})
        try:
            px = float(quote.get("price", 0))
        except:
            px = None
        t = classify_trend(ma20, ma60, px)
        trend_count[t] = trend_count.get(t, 0) + 1
    
    fuse_str = "🛑熔断" if _strategy_state.get("fuseBlown") else "✅正常"
    loss_str = f"连亏{_strategy_state['consecutiveLosses']}笔" if _strategy_state["consecutiveLosses"] > 0 else ""
    panorama.append(f"  趋势分布: 🟢多头{trend_count.get('BULL',0)}只 | 🔴空头{trend_count.get('BEAR',0)}只 | 🟡震荡{trend_count.get('RANGE',0)}只")
    panorama.append(f"  风控状态: {fuse_str} {loss_str} | 冷却中: {len(_strategy_state['coolingUntil'])}只 | 未配对: {sum(1 for s in signals_data.get('stocks',{}).values() if s.get('pendingSignal'))}笔")
    panorama.append("")
    
    for code in ALL_CODES:
        name = STOCK_NAMES.get(code, code)
        if code in T0_DISABLED:
            panorama.append(f"    {name}: 🔇 T+0禁用（仅监控）")
            continue
        state = signals_data["stocks"].get(code)
        if not state:
            # 无信号但有趋势信息
            ma_data_item = ma_map.get(code, {})
            ma20 = ma60 = None
            if ma_data_item:
                for key, val in ma_data_item.items():
                    if "ma_20" in key.lower() and val and val != "-":
                        try: ma20 = float(val)
                        except: pass
                    elif "ma_60" in key.lower() and val and val != "-":
                        try: ma60 = float(val)
                        except: pass
            q = quotes.get(code, {})
            try: px = float(q.get("price", 0))
            except: px = None
            t = classify_trend(ma20, ma60, px)
            trend_icon = {"BULL": "🟢", "BEAR": "🔴", "RANGE": "🟡"}.get(t, "⚪")
            panorama.append(f"    {name}: {trend_icon}{t} 无信号")
            continue

        parts = []
        for r in state.get("completedRounds", []):
            tag = "⚡" if r.get("forceclose") else "✅"
            parts.append(f"{tag}第{r['round']}轮{r['type']}(+{r['netReturn']:.2f}%)")

        pending = state.get("pendingSignal")
        if pending:
            leg_desc = "低吸" if pending["signalType"] == "low" else "高抛"
            elapsed = _minutes_since(pending["time"])
            trend_info = f"|趋势{pending.get('trend','?')}" if pending.get('trend') else ""
            strength_stars = "★" * pending.get('strength', 0) if pending.get('strength') else ""
            parts.append(f"⏳第{pending['round']}轮{pending['type']}等待配对({pending['time']}{leg_desc}@{pending['price']} 已等{elapsed}分钟{trend_info}{strength_stars})")

        if parts:
            panorama.append(f"    {name}: {' | '.join(parts)}")

    output_lines.extend(panorama)

    # 保存信号数据
    save_signals(signals_data)

    # 写入行情快照
    write_snapshot(quotes, techs, funds)

    # 输出结果
    if has_signal:
        for line in output_lines:
            print(line)
    else:
        print(f"✅ T+0盯盘 | 策略:VWAP共振 | {now_cst()} | 阶段:{phase} | 🟢{trend_count.get('BULL',0)}只多头 🔴{trend_count.get('BEAR',0)}只空头 🟡{trend_count.get('RANGE',0)}只震荡")

    # 写入心跳
    write_heartbeat(0, has_signal, 0, len(quotes))

    # 生成仪表盘HTML
    _generate_dashboard()

    # 15:00收盘总结
    now = datetime.now()
    if now.hour == 15 and now.minute >= 0 and now.minute < 10:
        print_daily_report(signals_data)


def _minutes_since(time_str):
    """计算从指定时间（HH:MM格式）到现在经过的分钟数"""
    try:
        h, m = map(int, time_str.split(":"))
        now = datetime.now()
        then = now.replace(hour=h, minute=m, second=0, microsecond=0)
        delta = (now - then).total_seconds() / 60
        return max(int(delta), 0)
    except Exception:
        return 0


def _force_close_pending(signals_data, quotes, phase):
    """强制闭环：对所有未配对仓位生成反向信号并配对
    
    phase="forceclose"(14:30-14:50): 优先配对，但仍尝试找合理价位
    phase="hardclose"(14:50+): 无条件按市价平仓，不管盈亏
    """
    msgs = []
    
    for code in ALL_CODES:
        if code in T0_DISABLED:
            continue
            
        stock_state = signals_data.get("stocks", {}).get(code)
        if not stock_state:
            continue
            
        pending = stock_state.get("pendingSignal")
        if not pending:
            continue
            
        name = STOCK_NAMES.get(code, code)
        quote = quotes.get(code, {})
        if not quote:
            continue
            
        try:
            current_price = float(quote.get("price", quote.get("currentPrice", 0)))
        except (ValueError, TypeError):
            continue
            
        if current_price <= 0:
            continue
        
        time_str = now_cst()
        
        # 计算配对结果
        if pending["signalType"] == "low":
            # 正T：低吸后高抛
            spread = (current_price - pending["price"]) / pending["price"] * 100
            net_return = spread - ROUND_TRIP_COST * 100
            pair = {
                "round": pending["round"],
                "type": "正T",
                "buyTime": pending["time"],
                "buyPrice": pending["price"],
                "sellTime": time_str,
                "sellPrice": current_price,
                "spread": round(spread, 2),
                "netReturn": round(net_return, 2),
                "forceclose": True,
                "forceclosePhase": phase,
            }
            tag = "⚠️硬截止平仓" if phase == "hardclose" else "⚡强制收尾"
            msgs.append(
                f"  【{tag} — 正T】\n"
                f"  {name}({code}): 第{pending['round']}轮正T 强制闭环\n"
                f"    {pending['time']}低吸@{pending['price']} → {time_str}高抛@{current_price}\n"
                f"    差价：{spread:+.2f}% | 扣费后净收益：{net_return:+.2f}%\n"
                f"    📌 底仓保持不变，T仓已闭环"
            )
        else:
            # 反T：高抛后低吸
            spread = (pending["price"] - current_price) / pending["price"] * 100
            net_return = spread - ROUND_TRIP_COST * 100
            pair = {
                "round": pending["round"],
                "type": "反T",
                "sellTime": pending["time"],
                "sellPrice": pending["price"],
                "buyTime": time_str,
                "buyPrice": current_price,
                "spread": round(spread, 2),
                "netReturn": round(net_return, 2),
                "forceclose": True,
                "forceclosePhase": phase,
            }
            tag = "⚠️硬截止平仓" if phase == "hardclose" else "⚡强制收尾"
            msgs.append(
                f"  【{tag} — 反T】\n"
                f"  {name}({code}): 第{pending['round']}轮反T 强制闭环\n"
                f"    {pending['time']}高抛@{pending['price']} → {time_str}低吸@{current_price}\n"
                f"    差价：{spread:+.2f}% | 扣费后净收益：{net_return:+.2f}%\n"
                f"    📌 底仓保持不变，T仓已闭环"
            )
        
        stock_state["completedRounds"].append(pair)
        signals_data["completedPairs"].append({
            "stock": name, "code": code, **pair
        })
        stock_state["pendingSignal"] = None
        signals_data["stocks"][code] = stock_state
        
        # 强制闭环通知（高优先级）
        notify_signal("high" if pending["signalType"] == "low" else "low",
                     name, current_price, f"强制平仓",
                     f"底仓不变 | 净{net_return:+.2f}%")
    
    return msgs

def print_daily_report(data):
    """输出今日T+0收盘日报"""
    total_pairs = len(data.get("completedPairs", []))
    total_return = sum(p.get("netReturn", 0) for p in data.get("completedPairs", []))
    total_signals = len(data.get("allSignals", []))

    print(f"\n{'='*50}")
    print(f"📊 T+0 盯盘日报 | {today_str()}")
    print(f"{'='*50}")
    print(f"\n═══ 策略概况 ═══")
    print(f"策略引擎：VWAP锚定 + 多信号共振 (v2.0)")
    print(f"信号冷却：{SIGNAL_COOLDOWN_MINUTES}分钟 | 单笔仓位：底仓{int(MAX_POSITION_RATIO*100)}% | 硬止损：{HARD_STOP_LOSS}%")
    fuse = "🛑已熔断" if _strategy_state.get("fuseBlown") else "✅正常"
    print(f"风控状态：{fuse} | 连续亏损：{_strategy_state.get('consecutiveLosses', 0)}笔")
    print(f"\n═══ 今日T+0战绩 ═══")
    print(f"完成T+0轮次：{total_pairs} 轮")
    print(f"今日预估T+0总收益：+{total_return:.2f}%（扣费后）")

    print(f"\n个股明细：")
    for code in ALL_CODES:
        name = STOCK_NAMES.get(code, code)
        if code in T0_DISABLED:
            print(f"  {name}: 🔇 T+0禁用（仅监控行情）")
            continue
        state = data["stocks"].get(code)
        if not state or not state.get("completedRounds"):
            pending = state.get("pendingSignal") if state else None
            if pending:
                elapsed = _minutes_since(pending["time"])
                print(f"  {name}: ⚠️未完成 - 第{pending['round']}轮{pending['type']}仅完成{'低吸' if pending['signalType']=='low' else '高抛'}@{pending['price']} (已等{elapsed}分钟)")
            continue

        rounds = state["completedRounds"]
        stock_return = sum(r["netReturn"] for r in rounds)
        forced = sum(1 for r in rounds if r.get("forceclose"))
        zheng = sum(1 for r in rounds if r["type"] == "正T")
        fan = sum(1 for r in rounds if r["type"] == "反T")
        type_str = []
        if zheng: type_str.append(f"正T×{zheng}")
        if fan: type_str.append(f"反T×{fan}")
        if forced: type_str.append(f"强制平仓×{forced}")
        print(f"  {name}: {len(rounds)}轮完成 | {' | '.join(type_str)} | 净收益+{stock_return:.2f}%")

        for r in rounds:
            tag = "⚡" if r.get("forceclose") else ""
            if r["type"] == "正T":
                print(f"    - {tag}第{r['round']}轮正T: {r['buyTime']}买@{r['buyPrice']} → {r['sellTime']}卖@{r['sellPrice']} (+{r['netReturn']:.2f}%)")
            else:
                print(f"    - {tag}第{r['round']}轮反T: {r['sellTime']}卖@{r['sellPrice']} → {r['buyTime']}买@{r['buyPrice']} (+{r['netReturn']:.2f}%)")

    print(f"\n今日信号触发统计：")
    low_count = sum(1 for s in data["allSignals"] if s["type"] == "low")
    high_count = sum(1 for s in data["allSignals"] if s["type"] == "high")
    pair_rate = total_pairs / max(total_signals, 1) * 100
    print(f"  低吸信号：{low_count}次 | 高抛信号：{high_count}次 | 配对成功率：{pair_rate:.0f}%")
    print(f"{'='*50}")

    # 同时生成HTML报告
    generate_html_report(data)

def generate_html_report(data, quotes=None):
    """生成每日T+0盯盘HTML报告，包含盈亏分析"""
    report_dir = os.path.join(SIGNALS_DIR, "reports")
    os.makedirs(report_dir, exist_ok=True)

    date_str = data.get("date", today_str())
    filepath = os.path.join(report_dir, f"{date_str}-T0日报.html")

    # ======== 数据计算 ========
    completed = data.get("completedPairs", [])
    total_pairs = len(completed)
    winning = [p for p in completed if p.get("netReturn", 0) > 0]
    losing = [p for p in completed if p.get("netReturn", 0) <= 0]
    total_return = sum(p.get("netReturn", 0) for p in completed)
    win_rate = len(winning) / max(total_pairs, 1) * 100
    avg_return = total_return / max(total_pairs, 1)

    # 未完成配对
    unpaired = []
    for code, state in data.get("stocks", {}).items():
        pending = state.get("pendingSignal")
        if pending:
            unpaired.append({
                "stock": state.get("name", STOCK_NAMES.get(code, code)),
                "code": code,
                "type": pending.get("type", ""),
                "signalType": pending.get("signalType", ""),
                "price": pending.get("price", 0),
                "time": pending.get("time", ""),
                "round": pending.get("round", 0),
            })

    # 个股汇总
    stock_stats = {}
    for pair in completed:
        code = pair.get("code", "")
        if code not in stock_stats:
            stock_stats[code] = {"name": pair.get("stock", STOCK_NAMES.get(code, code)), "rounds": 0, "total_return": 0, "pairs": [], "zheng": 0, "fan": 0}
        stock_stats[code]["rounds"] += 1
        stock_stats[code]["total_return"] += pair.get("netReturn", 0)
        stock_stats[code]["pairs"].append(pair)
        if pair.get("type") == "正T":
            stock_stats[code]["zheng"] += 1
        else:
            stock_stats[code]["fan"] += 1

    # 信号统计
    all_signals = data.get("allSignals", [])
    low_count = sum(1 for s in all_signals if s.get("type") == "low")
    high_count = sum(1 for s in all_signals if s.get("type") == "high")
    pair_rate = total_pairs / max(len(all_signals), 1) * 100

    # ======== 生成HTML ========
    # 个股收益条
    stock_bars_html = ""
    if stock_stats:
        sorted_stocks = sorted(stock_stats.items(), key=lambda x: x[1]["total_return"], reverse=True)
        max_ret = max((abs(s["total_return"]) for _, s in sorted_stocks), default=0.1)
        max_ret = max(max_ret, 0.1)
        for code, stats in sorted_stocks:
            ret = stats["total_return"]
            bar_width = abs(ret) / max_ret * 100
            css_class = "positive" if ret > 0 else "negative"
            stock_bars_html += f"""
            <div class="bar-row">
                <span class="bar-label">{stats['name']}</span>
                <div class="bar-track"><div class="bar-fill {css_class}" style="width:{bar_width}%"></div></div>
                <span class="bar-value {css_class}">{'+' if ret > 0 else ''}{ret:.2f}%</span>
            </div>"""

    # 交易明细行
    detail_rows = ""
    for pair in completed:
        ret = pair.get("netReturn", 0)
        spread = pair.get("spread", 0)
        css_class = "positive" if ret > 0 else "negative"
        force_tag = " ⚡强平" if pair.get("forceclose") else ""
        detail_rows += f"""
            <tr>
                <td>{pair.get('stock','')}{force_tag}</td>
                <td>第{pair.get('round',0)}轮</td>
                <td>{pair.get('type','')}</td>
                <td>{pair.get('buyTime','')}</td>
                <td>{pair.get('buyPrice',0)}</td>
                <td>{pair.get('sellTime','')}</td>
                <td>{pair.get('sellPrice',0)}</td>
                <td>{'+' if spread > 0 else ''}{spread:.2f}%</td>
                <td class="{css_class}">{'+' if ret > 0 else ''}{ret:.2f}%</td>
            </tr>"""

    # 未完成配对警告（强化：标注底仓风险）
    unpaired_html = ""
    if unpaired:
        unpaired_items = ""
        for u in unpaired:
            direction = "低吸(已买入)" if u["signalType"] == "low" else "高抛(已卖出)"
            t_type = u.get("type", "")
            risk = "T仓买入未卖出，底仓多出1份" if u["signalType"] == "low" else "T仓卖出未回补，底仓少1份"
            unpaired_items += f'<p>{u["stock"]}({u["code"]}): 第{u["round"]}轮{t_type} | {u["time"]}{direction}@{u["price"]} — 🔴{risk} | 系统将在14:30后强制平仓</p>\n'
        unpaired_html = f"""
    <div class="warning-box">
        <h3>⚠️ 未完成配对（{len(unpaired)}笔）— 底仓风险暴露</h3>
        <p style="color:#f85149;font-weight:bold;margin-bottom:10px;">T+0铁律：底仓不变！系统将在14:30后强制闭环，14:50前全部平仓</p>
        {unpaired_items}
    </div>"""

    # 无信号股票列表
    no_signal_stocks = []
    for code in ALL_CODES:
        name = STOCK_NAMES.get(code, code)
        if code not in stock_stats and code not in [u["code"] for u in unpaired]:
            no_signal_stocks.append(name)
    no_signal_html = ""
    if no_signal_stocks:
        no_signal_html = f"""
    <div class="info-box">
        <h3>💤 无信号股票</h3>
        <p>{'、'.join(no_signal_stocks)}</p>
    </div>"""

    # 全部信号时间线
    signal_timeline = ""
    for s in all_signals:
        direction = "🟢低吸" if s["type"] == "low" else "🔴高抛"
        css_class = "low" if s["type"] == "low" else "high"
        signal_timeline += f"""
            <tr class="signal-{css_class}">
                <td>{s.get('time','')}</td>
                <td>{direction}</td>
                <td>{s.get('stock','')}</td>
                <td>{s.get('price',0)}</td>
                <td>{s.get('details','')}</td>
                <td>{s.get('amplitude',0):.1f}%</td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>T+0 盯盘日报 | {date_str}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Microsoft YaHei', 'PingFang SC', sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
  .container {{ max-width: 1000px; margin: 0 auto; }}
  h1 {{ text-align: center; color: #58a6ff; margin-bottom: 5px; font-size: 26px; }}
  .date {{ text-align: center; color: #8b949e; margin-bottom: 30px; font-size: 14px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 30px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 18px; text-align: center; }}
  .card .label {{ font-size: 12px; color: #8b949e; margin-bottom: 6px; }}
  .card .value {{ font-size: 28px; font-weight: bold; }}
  .positive {{ color: #3fb950; }}
  .negative {{ color: #f85149; }}
  .neutral {{ color: #58a6ff; }}
  h2 {{ color: #58a6ff; margin: 30px 0 15px; font-size: 18px; border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px; }}
  th {{ background: #161b22; color: #8b949e; padding: 10px; text-align: left; border-bottom: 2px solid #30363d; white-space: nowrap; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #21262d; }}
  tr:hover {{ background: #161b22; }}
  .bar-row {{ display: flex; align-items: center; gap: 10px; margin: 6px 0; }}
  .bar-label {{ width: 80px; text-align: right; font-size: 13px; flex-shrink: 0; }}
  .bar-track {{ flex: 1; height: 22px; background: #21262d; border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s ease; }}
  .bar-fill.positive {{ background: linear-gradient(90deg, #238636, #3fb950); }}
  .bar-fill.negative {{ background: linear-gradient(90deg, #da3633, #f85149); }}
  .bar-value {{ width: 70px; font-size: 13px; font-weight: bold; }}
  .warning-box {{ background: #1c1204; border: 1px solid #9e6a03; border-radius: 10px; padding: 18px; margin: 20px 0; }}
  .warning-box h3 {{ color: #d29922; margin-bottom: 10px; font-size: 15px; }}
  .warning-box p {{ color: #e3b341; font-size: 13px; margin: 5px 0; }}
  .info-box {{ background: #0c1929; border: 1px solid #1f6feb; border-radius: 10px; padding: 18px; margin: 20px 0; }}
  .info-box h3 {{ color: #58a6ff; margin-bottom: 10px; font-size: 15px; }}
  .info-box p {{ color: #8b949e; font-size: 13px; }}
  .signal-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 15px 0; }}
  .signal-stats .stat {{ background: #161b22; padding: 12px; border-radius: 8px; text-align: center; }}
  .signal-stats .stat .label {{ font-size: 12px; color: #8b949e; }}
  .signal-stats .stat .value {{ font-size: 20px; font-weight: bold; color: #58a6ff; }}
  .signal-low {{ border-left: 3px solid #3fb950; }}
  .signal-high {{ border-left: 3px solid #f85149; }}
  .footer {{ text-align: center; color: #484f58; font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #21262d; }}
  .cost-note {{ color: #8b949e; font-size: 13px; margin: 10px 0; padding: 10px; background: #161b22; border-radius: 6px; }}
  @media (max-width: 600px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} body {{ padding: 10px; }} }}
</style>
</head>
<body>
<div class="container">
  <h1>T+0 盯盘日报</h1>
  <div class="date">{date_str} | 佣金万一+印花税万五=往返0.07%</div>

  <div class="cards">
    <div class="card">
      <div class="label">完成轮次</div>
      <div class="value neutral">{total_pairs}</div>
    </div>
    <div class="card">
      <div class="label">预估总收益（扣费后）</div>
      <div class="value {"positive" if total_return > 0 else "negative" if total_return < 0 else "neutral"}">{'+' if total_return > 0 else ''}{total_return:.2f}%</div>
    </div>
    <div class="card">
      <div class="label">胜率</div>
      <div class="value {"positive" if win_rate >= 50 else "negative"}">{win_rate:.0f}%</div>
    </div>
    <div class="card">
      <div class="label">平均每笔</div>
      <div class="value {"positive" if avg_return > 0 else "negative" if avg_return < 0 else "neutral"}">{'+' if avg_return > 0 else ''}{avg_return:.2f}%</div>
    </div>
  </div>

  <h2>📈 个股收益排行</h2>
  {stock_bars_html}

  <h2>📋 交易明细（已配对）</h2>
  <table>
    <tr><th>股票</th><th>轮次</th><th>类型</th><th>买入时间</th><th>买入价</th><th>卖出时间</th><th>卖出价</th><th>差价</th><th>净收益</th></tr>
    {detail_rows if detail_rows else '<tr><td colspan="9" style="text-align:center;color:#484f58;">今日无已完成配对</td></tr>'}
  </table>

  {unpaired_html}
  {no_signal_html}

  <h2>📊 信号统计</h2>
  <div class="signal-stats">
    <div class="stat"><div class="label">低吸信号</div><div class="value">{low_count}次</div></div>
    <div class="stat"><div class="label">高抛信号</div><div class="value">{high_count}次</div></div>
    <div class="stat"><div class="label">配对成功率</div><div class="value">{pair_rate:.0f}%</div></div>
    <div class="stat"><div class="label">盈利/亏损</div><div class="value">{len(winning)}/{len(losing)}</div></div>
  </div>

  <h2>🕐 全部信号时间线</h2>
  <table>
    <tr><th>时间</th><th>方向</th><th>股票</th><th>价格</th><th>触发条件</th><th>振幅</th></tr>
    {signal_timeline if signal_timeline else '<tr><td colspan="6" style="text-align:center;color:#484f58;">今日无信号</td></tr>'}
  </table>

  <div class="cost-note">
    💰 交易成本：佣金万一（双向）+ 印花税万五（卖出单边）= 往返0.07% | 净收益已扣除全部交易成本 | 净收益目标>0.6%/笔
  </div>

  <div class="footer">
    T+0 日内盯盘系统 | 数据来源：westock-data | 仅供参考，不构成投资建议
  </div>
</div>
</body>
</html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    log(f"📊 日报已保存: {filepath}")

    # 通知并自动打开浏览器
    notify_daily_report(filepath)
    try:
        import webbrowser
        webbrowser.open(filepath)
    except Exception:
        pass

    return filepath

# ═══════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="T+0 日内盯盘脚本")
    parser.add_argument("--once", action="store_true", help="只执行一次检查")
    parser.add_argument("--interval", type=int, default=300, help="检查间隔秒数（默认300=5分钟）")
    parser.add_argument("--test", action="store_true", help="测试模式：忽略交易时段和交易日限制")
    parser.add_argument("--data-dir", type=str, default=None, help="数据目录（存放信号文件和日志，默认脚本同级data/）")
    args = parser.parse_args()

    # 覆盖数据目录
    if args.data_dir:
        global SIGNALS_DIR, SIGNALS_FILE, LOG_FILE, PID_FILE, HOLIDAYS_FILE
        global HEARTBEAT_FILE, SNAPSHOT_FILE, HISTORY_DIR
        SIGNALS_DIR = args.data_dir
        SIGNALS_FILE = os.path.join(SIGNALS_DIR, "t0-signals-today.json")
        LOG_FILE = os.path.join(SIGNALS_DIR, "t0-monitor.log")
        PID_FILE = os.path.join(SIGNALS_DIR, "t0-monitor.pid")
        HOLIDAYS_FILE = os.path.join(SIGNALS_DIR, "holidays.txt")
        HEARTBEAT_FILE = os.path.join(SIGNALS_DIR, "t0-heartbeat.json")
        SNAPSHOT_FILE = os.path.join(SIGNALS_DIR, "t0-snapshot.json")
        HISTORY_DIR = os.path.join(SIGNALS_DIR, "history")

    os.makedirs(SIGNALS_DIR, exist_ok=True)

    # 非测试模式下，检查是否交易日
    if not args.test and not args.once:
        if not is_trading_day():
            log(f".today非交易日（周末或节假日），自动退出")
            return

    # 非测试模式下，检查重复实例
    if not args.test and not args.once:
        if check_already_running():
            print("T+0盯盘已有实例在运行，跳过重复启动")
            return

    print("=" * 50)
    print(f"T+0 日内盯盘系统 | 启动于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"检查间隔：{args.interval}秒 | 标的：{len(ALL_CODES)}只")
    print(f"交易成本：佣金万一+印花税万五=往返{ROUND_TRIP_COST*100:.2f}%")
    print(f"每单目标：净收益>{MIN_PROFIT_TARGET*100:.1f}%（差价>{MIN_SPREAD*100:.2f}%）")
    print("=" * 50)

    if args.once or args.test:
        if args.test:
            # 测试模式：临时修改交易时段判断
            global is_trading_hours
            is_trading_hours = lambda: True
        run_check()
        return

    # 持续运行模式：写入PID
    write_pid()

    try:
        check_count = 0
        while True:
            try:
                if is_trading_hours():
                    check_count += 1
                    log(f"═══ 第{check_count}次检查 ═══")
                    run_check()
                    # 更新心跳中的检查次数
                    try:
                        with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
                            hb = json.load(f)
                        hb["checkCount"] = check_count
                        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
                            json.dump(hb, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                else:
                    # 非交易时段
                    now = datetime.now()

                    # 收盘后15:00-15:05：做最后一次检查+生成日报
                    if now.hour == 15 and now.minute < 5 and check_count > 0:
                        log("📊 收盘后最终检查，生成日报...")
                        run_check(force=True)  # force=True忽略交易时段限制
                        signals_data = load_signals()
                        if signals_data:
                            print_daily_report(signals_data)
                        check_count = 0  # 避免重复触发

                    # 计算距离下次开盘的等待时间
                    next_start = None
                    for sh, sm, eh, em in TRADING_SESSIONS:
                        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                        if start > now:
                            next_start = start
                            break
                    if next_start is None:
                        # 今天没有更多交易时段
                        # 如果已过15:05，自动退出（明天由计划任务重新启动）
                        if now.hour >= 15 and now.minute >= 5:
                            log("📊 今日收盘，监控进程自动退出（明天09:25由计划任务启动）")
                            # 生成最后一次仪表盘
                            _generate_dashboard()
                            # 收盘日报：直接读取今日信号数据生成报告
                            # （不能调run_check因为15:00后is_trading_hours()返回False）
                            signals_data = load_signals()
                            if signals_data:
                                print_daily_report(signals_data)
                            break
                        # 午休时段（11:30-13:00），等到下午开盘
                        next_start = now.replace(hour=13, minute=0, second=0, microsecond=0)
                        if next_start <= now:
                            next_start = (now + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)

                    wait_secs = (next_start - now).total_seconds()
                    if wait_secs > 60:
                        log(f"⏸️ 非交易时段，下次开盘：{next_start.strftime('%H:%M')}，等待{wait_secs/60:.0f}分钟")
                        time.sleep(min(wait_secs - 30, 300))  # 最多等5分钟再检查
                        continue

                time.sleep(args.interval)

            except KeyboardInterrupt:
                log("用户中断，退出")
                break
            except Exception as e:
                log(f"异常：{e}")
                time.sleep(60)
    finally:
        remove_pid()
        log("T+0盯盘已退出")

if __name__ == "__main__":
    main()
