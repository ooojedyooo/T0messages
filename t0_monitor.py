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

# 交易成本
COMMISSION_RATE = 0.0001    # 万一 买卖双边
STAMP_TAX_RATE = 0.0005     # 万五 卖出单边
ROUND_TRIP_COST = COMMISSION_RATE * 2 + STAMP_TAX_RATE  # 0.07%
MIN_PROFIT_TARGET = 0.006   # 0.6% 净收益目标
MIN_SPREAD = MIN_PROFIT_TARGET + ROUND_TRIP_COST  # 0.67% 最小差价

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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode == 0 and result.stdout.strip():
            parsed = parse_markdown_table(result.stdout)
            if parsed:
                return parsed
            # 如果表格解析失败，返回None
            return None
        else:
            if result.stderr:
                log(f"  CLI错误: {result.stderr[:150]}")
            return None
    except subprocess.TimeoutExpired:
        log(f"  CLI超时: {' '.join(args[:3])}")
        return None
    except Exception as e:
        log(f"  CLI异常: {e}")
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
    return quotes, techs, funds

# ═══════════════════════════════════════════════════
# 信号判断
# ═══════════════════════════════════════════════════

def check_low_signal(quote, tech, fund):
    """检查低吸信号，返回满足的条件数和详情"""
    conditions = 0
    details = []

    # 条件1: RSI6 < 35 或 RSI6较开盘时明显下降
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
        if rsi6 < 35:
            conditions += 1
            details.append(f"RSI6={rsi6:.1f}")

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

    # 条件5: 主力净流出在收窄
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
        if net_amount > 0 or (net_amount < 0 and abs(net_amount) < 5000000):
            conditions += 1
            details.append("主力流出收窄")

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

    # 条件5: 主力净流入在收窄
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
        if net_amount < 0 or (net_amount > 0 and net_amount < 5000000):
            conditions += 1
            details.append("主力流入收窄")

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
    """初始化今日信号"""
    return {
        "date": today_str(),
        "stocks": {},
        "allSignals": [],
        "completedPairs": [],
    }

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
            # 同向信号，更新首笔（取更优价格）
            if signal_type == "low" and price < pending["price"]:
                pending["price"] = price
                pending["time"] = time_str
                result_msg = f"  [更新] {name}({code}) 低吸信号价格更新为 {price}"
            elif signal_type == "high" and price > pending["price"]:
                pending["price"] = price
                pending["time"] = time_str
                result_msg = f"  [更新] {name}({code}) 高抛信号价格更新为 {price}"
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

def run_check():
    """执行一次完整的T+0信号检查"""
    global _check_count
    if not is_trading_hours():
        log("⏸️ 非交易时段，跳过")
        write_heartbeat(getattr(run_check, '_count', 0), False, 0, 0, "非交易时段")
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
        return

    output_lines = [f"\n🎯 T+0交易信号 | {now_cst()}"]
    has_signal = False
    signaled_codes = set()  # 本轮已触发信号的股票，防止同时触发低吸+高抛自我配对

    for code in ALL_CODES:
        quote = quotes.get(code, {})
        tech = techs.get(code, {})
        fund = funds.get(code, {})

        if not quote:
            continue

        # 提取关键数据
        try:
            price = float(quote.get("price", quote.get("currentPrice", 0)))
            low = float(quote.get("low", quote.get("todayLow", 0)))
            high = float(quote.get("high", quote.get("todayHigh", 0)))
            change_pct = float(quote.get("changePercent", quote.get("change_pct", 0)))
        except (ValueError, TypeError):
            continue

        if price <= 0:
            continue

        amplitude = (high - low) / low * 100 if low > 0 else 0

        # 检查低吸信号
        low_cond, low_details = check_low_signal(quote, tech, fund)
        if low_cond >= 2:
            rating_int, rating_str = calc_rating(amplitude)
            msg = process_signal(signals_data, code, "low", price, rating_int, low_details, amplitude)
            signaled_codes.add(code)
            output_lines.append(msg)
            has_signal = True

        # 检查高抛信号（本轮已触发信号的不再检查，防止自我配对）
        if code not in signaled_codes:
            high_cond, high_details = check_high_signal(quote, tech, fund)
            if high_cond >= 2:
                rating_int, rating_str = calc_rating(amplitude)
                msg = process_signal(signals_data, code, "high", price, rating_int, high_details, amplitude)
                signaled_codes.add(code)
                output_lines.append(msg)
                has_signal = True

    # 今日T+0全景
    panorama = ["\n  【📋 今日T+0全景】"]
    for code in ALL_CODES:
        name = STOCK_NAMES.get(code, code)
        state = signals_data["stocks"].get(code)
        if not state:
            panorama.append(f"    {name}: 无信号")
            continue

        parts = []
        for r in state.get("completedRounds", []):
            parts.append(f"✅第{r['round']}轮{r['type']}(+{r['netReturn']:.2f}%)")

        pending = state.get("pendingSignal")
        if pending:
            leg_desc = "低吸" if pending["signalType"] == "low" else "高抛"
            parts.append(f"⏳第{pending['round']}轮{pending['type']}等待配对({pending['time']}{leg_desc}@{pending['price']})")

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
        print(f"✅ T+0盯盘 | 15只标的均无信号 | {now_cst()}")

    # 写入心跳
    write_heartbeat(0, has_signal, len(signaled_codes), len(quotes))

    # 15:00收盘总结
    now = datetime.now()
    if now.hour == 15 and now.minute >= 0 and now.minute < 6:
        print_daily_report(signals_data)

def print_daily_report(data):
    """输出今日T+0收盘日报"""
    total_pairs = len(data.get("completedPairs", []))
    total_return = sum(p.get("netReturn", 0) for p in data.get("completedPairs", []))
    total_signals = len(data.get("allSignals", []))

    print(f"\n{'='*50}")
    print(f"📊 T+0 盯盘日报 | {today_str()}")
    print(f"{'='*50}")
    print(f"\n═══ 今日T+0战绩 ═══")
    print(f"完成T+0轮次：{total_pairs} 轮")
    print(f"今日预估T+0总收益：+{total_return:.2f}%（扣费后）")

    print(f"\n个股明细：")
    for code in ALL_CODES:
        name = STOCK_NAMES.get(code, code)
        state = data["stocks"].get(code)
        if not state or not state.get("completedRounds"):
            pending = state.get("pendingSignal") if state else None
            if pending:
                print(f"  {name}: 未完成 - 第{pending['round']}轮{pending['type']}仅完成{'低吸' if pending['signalType']=='low' else '高抛'}@{pending['price']}")
            continue

        rounds = state["completedRounds"]
        stock_return = sum(r["netReturn"] for r in rounds)
        zheng = sum(1 for r in rounds if r["type"] == "正T")
        fan = sum(1 for r in rounds if r["type"] == "反T")
        type_str = []
        if zheng: type_str.append(f"正T×{zheng}")
        if fan: type_str.append(f"反T×{fan}")
        print(f"  {name}: {len(rounds)}轮完成 | {' | '.join(type_str)} | 净收益+{stock_return:.2f}%")

        for r in rounds:
            if r["type"] == "正T":
                print(f"    - 第{r['round']}轮正T: {r['buyTime']}买@{r['buyPrice']} → {r['sellTime']}卖@{r['sellPrice']} (+{r['netReturn']:.2f}%)")
            else:
                print(f"    - 第{r['round']}轮反T: {r['sellTime']}卖@{r['sellPrice']} → {r['buyTime']}买@{r['buyPrice']} (+{r['netReturn']:.2f}%)")

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
        detail_rows += f"""
            <tr>
                <td>{pair.get('stock','')}</td>
                <td>第{pair.get('round',0)}轮</td>
                <td>{pair.get('type','')}</td>
                <td>{pair.get('buyTime','')}</td>
                <td>{pair.get('buyPrice',0)}</td>
                <td>{pair.get('sellTime','')}</td>
                <td>{pair.get('sellPrice',0)}</td>
                <td>{'+' if spread > 0 else ''}{spread:.2f}%</td>
                <td class="{css_class}">{'+' if ret > 0 else ''}{ret:.2f}%</td>
            </tr>"""

    # 未完成配对警告
    unpaired_html = ""
    if unpaired:
        unpaired_items = ""
        for u in unpaired:
            direction = "低吸" if u["signalType"] == "low" else "高抛"
            unpaired_items += f'<p>{u["stock"]}({u["code"]}): 第{u["round"]}轮{u["type"]} | {u["time"]}{direction}@{u["price"]} — 收盘未配对，需持股过夜或次日处理</p>\n'
        unpaired_html = f"""
    <div class="warning-box">
        <h3>⚠️ 未完成配对（{len(unpaired)}笔）</h3>
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
        SIGNALS_DIR = args.data_dir
        SIGNALS_FILE = os.path.join(SIGNALS_DIR, "t0-signals-today.json")
        LOG_FILE = os.path.join(SIGNALS_DIR, "t0-monitor.log")
        PID_FILE = os.path.join(SIGNALS_DIR, "t0-monitor.pid")
        HOLIDAYS_FILE = os.path.join(SIGNALS_DIR, "holidays.txt")

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
                    # 非交易时段，计算距离下次开盘的等待时间
                    now = datetime.now()
                    next_start = None
                    for sh, sm, eh, em in TRADING_SESSIONS:
                        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                        if start > now:
                            next_start = start
                            break
                    if next_start is None:
                        # 今天没有更多交易时段，等到明天
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
