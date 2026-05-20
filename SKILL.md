---
name: T0盯盘
description: A股T+0日内盯盘信号系统。触发词：盯盘、T+0、启动盯盘、开始盯盘、跑盯盘、看信号、看盘、检查信号、盯盘启动。当用户需要实时监控持仓股票的T+0交易机会时使用此技能。本地Python脚本运行，不消耗WorkBuddy token。
---

# T+0 日内盯盘信号系统

## 概述

本地Python脚本驱动的A股T+0日内盯盘系统，交易时段每5分钟扫描15只底仓股票，输出成对交易信号（低吸+高抛），保持底仓不变赚取超额收益。**纯本地运行，不消耗WorkBuddy token。** 信号触发时自动推送通知（声音+桌面弹窗+可选微信推送），15:00收盘自动生成HTML盈亏日报。

## 核心参数

| 参数 | 值 |
|------|-----|
| 检查间隔 | 5分钟（可调） |
| 交易成本 | 佣金万一（双向）+ 印花税万五（卖出单边）= 往返0.07% |
| 最小差价 | 0.67%（覆盖成本+0.6%净收益目标） |
| 净收益目标 | >0.6%/笔 |
| 信号触发 | 低吸6条件满足2+/高抛6条件满足2+ |
| 评级 | ⭐⭐⭐净>1.5% / ⭐⭐净0.6-1.5% / ⭐净<0.6%（跳过）|

## 监控标的（15只，2组）

**A组（8只）**：比亚迪(sz002594)、宁德时代(sz300750)、海光信息(sh688041)、中际旭创(sz300308)、新易盛(sz300502)、杰普特(sh688025)、福晶科技(sz002222)、通富微电(sz002156)

**B组（7只）**：聚和材料(sh688503)、迈威生物(sh688062)、江苏雷利(sz300660)、厦钨新能(sh688778)、先导智能(sz300450)、东材科技(sh601208)、亿纬锂能(sz300014)

## 信号判断逻辑

### 低吸信号（6条件，满足2+触发）
1. RSI6 < 35
2. 当日跌幅 > 1.0%
3. 股价距当日低点不到1%
4. MACD柱状线绿柱缩短或即将翻红
5. 主力净流出收窄
6. 量比 < 0.8

### 高抛信号（6条件，满足2+触发）
1. RSI6 > 65
2. 当日涨幅 > 1.0%
3. 股价距当日高点不到1%
4. MACD柱状线红柱缩短或即将翻绿
5. 主力净流入收窄
6. 换手率 > 3%

### 交易类型
- **正T**（先买后卖）：首笔触发低吸→等高抛配对
- **反T**（先卖后买）：首笔触发高抛→等低吸配对
- 每只股票每天可多轮T+0，配对完成后立即开始新一轮

### 输出格式
- 第N轮T+0 | 第X笔/共2笔
- 目标价位：最低（覆盖成本）/ 合理（振幅×0.5）/ 乐观
- 15:00自动输出收盘日报 + 生成HTML盈亏报告

## 通知推送系统

信号触发时自动推送通知，确保不错过交易机会：

| 通知方式 | 默认 | 说明 | 配置项 |
|---------|------|------|--------|
| 🔊 声音提醒 | ✅开 | 低吸=上升音调，高抛=下降音调，配对完成=连续提示音 | `NOTIFICATION_SOUND` |
| 💬 桌面弹窗 | ✅开 | Windows 10/11右下角弹窗，显示股票名称和信号类型 | `NOTIFICATION_TOAST` |
| 📱 微信推送 | ❌关 | PushPlus推送至微信（需注册获取token） | `PUSHPLUS_TOKEN` |
| 📱 Server酱 | ❌关 | Server酱推送（需注册获取SendKey） | `SERVERCHAN_KEY` |

### 声音区分
- 🟢低吸信号：上升音调（低→高），三声递进
- 🔴高抛信号：下降音调（高→低），三声递进
- ✅配对完成：与对应方向相同的提示音
- 📊收盘日报：三声短促提示音

### 开启微信推送（可选）
1. 注册 [PushPlus](https://www.pushplus.plus/)（免费，每天200条额度）
2. 获取token后填入脚本配置 `PUSHPLUS_TOKEN = "你的token"`
3. 信号触发后微信即时收到推送

或使用 [Server酱](https://sct.ftqq.com/)：
1. 注册获取SendKey
2. 填入 `SERVERCHAN_KEY = "你的SendKey"`

## 每日盈亏HTML报告

15:00收盘自动生成HTML日报，包含：

1. **总览卡片**：完成轮次、预估总收益（扣费后）、胜率、平均每笔收益
2. **个股收益排行**：绿色=盈利/红色=亏损的可视化条形图
3. **交易明细表**：每笔配对的买入/卖出时间、价格、差价、净收益
4. **未完成配对警告**：⚠️ 收盘前未等到配对的首笔信号
5. **信号统计**：低吸/高抛信号次数、配对成功率、盈亏比
6. **全部信号时间线**：当日触发的所有信号按时间排列

报告保存位置：`D:\T0交易提醒\data\reports\YYYY-MM-DD-T0日报.html`
生成后自动在浏览器打开。

## 自动启停（Windows计划任务）

已配置两个Windows计划任务，**交易日自动启停，完全无需手动操作**：

| 任务 | 时间 | 操作 |
|------|------|------|
| T0盯盘-启动 | 周一至周五 09:25 | 后台静默启动监控脚本 |
| T0盯盘-关闭 | 周一至周五 15:05 | 优雅终止监控进程 |

### 启停脚本

- **启动脚本**：`D:\T0交易提醒\t0_start.ps1` — 使用 `Start-Process -WindowStyle Hidden` 静默启动
- **停止脚本**：`D:\T0交易提醒\t0_stop.ps1` — 读取PID文件终止进程，备用方案按进程名查找
- **VBS启动器**：`D:\T0交易提醒\t0_start_silent.vbs` — 备用方案（VBS方式启动）

### 交易日判断（双重保险）

1. **计划任务层**：仅周一至周五触发
2. **脚本层**：Python脚本启动时检查 `is_trading_day()`，非交易日（周末+节假日）自动退出

### 节假日配置

编辑 `D:\T0交易提醒\data\holidays.txt`，每行一个日期（YYYY-MM-DD），以 `#` 开头的行为注释：
```
# 2026年节假日
2026-01-01  元旦
2026-10-01  国庆节
```
**每年更新一次**，参考沪深交易所公告。

### PID管理

- 启动时写入 `D:\T0交易提醒\data\t0-monitor.pid`
- 退出时自动清理
- 防重复启动：检测到已有实例运行时跳过

### 手动操作

```bash
# 手动启动（静默后台运行）
powershell -ExecutionPolicy Bypass -File D:/T0交易提醒/t0_start.ps1

# 手动停止
powershell -ExecutionPolicy Bypass -File D:/T0交易提醒/t0_stop.ps1

# 查看计划任务状态
Get-ScheduledTask -TaskName "T0盯盘*"

# 查看是否在运行
cat D:/T0交易提醒/data/t0-monitor.pid
```

### 计划任务管理

```powershell
# 查看任务
Get-ScheduledTask -TaskName "T0盯盘*"

# 手动触发启动任务
Start-ScheduledTask -TaskName "T0盯盘-启动"

# 手动触发停止任务
Start-ScheduledTask -TaskName "T0盯盘-关闭"

# 暂停/恢复（如长假期间）
Disable-ScheduledTask -TaskName "T0盯盘-启动"
Disable-ScheduledTask -TaskName "T0盯盘-关闭"
Enable-ScheduledTask -TaskName "T0盯盘-启动"
Enable-ScheduledTask -TaskName "T0盯盘-关闭"
```

## 执行命令

### 启动持续盯盘（交易时段5分钟循环）
```bash
python D:/T0交易提醒/t0_monitor.py
```

### 单次检查
```bash
python D:/T0交易提醒/t0_monitor.py --once
```

### 测试模式（忽略交易时段和交易日限制）
```bash
python D:/T0交易提醒/t0_monitor.py --test --once
```

### 自定义间隔（如10分钟）
```bash
python D:/T0交易提醒/t0_monitor.py --interval 600
```

### 指定数据目录
```bash
python D:/T0交易提醒/t0_monitor.py --data-dir D:/t0-data
```

## 数据源

使用 westock-data CLI（本地已安装插件）：
- `quote` — 实时行情（价格/涨跌幅/高低/量比/换手率）
- `technical --group macd,rsi,ma` — 技术指标（RSI6/MACD）
- `asfund` — A股资金流向（主力净流入/流出）

CLI路径：`C:\Users\Ryan\.workbuddy\plugins\marketplaces\cb_teams_marketplace\plugins\finance-data\skills\westock-data\scripts\index.js`

## 状态持久化

- 信号文件：`D:\T0交易提醒\data\t0-signals-today.json`
- 日志文件：`D:\T0交易提醒\data\t0-monitor.log`
- HTML日报：`D:\T0交易提醒\data\reports\YYYY-MM-DD-T0日报.html`
- 每日自动重置（按日期判断）
- 配对状态跨检查周期保留

## ⚠️ 重要注意事项

### 防止自我配对
同一检查周期内，同一只股票只触发一个方向信号（低吸或高抛），防止自己跟自己配对。

### westock-data CLI 返回Markdown
CLI输出是Markdown表格而非JSON，脚本内置了 `parse_markdown_table()` 解析器。如果CLI格式变化，需更新解析逻辑。

### 同向信号更新
如果已有未配对信号，再收到同方向信号时，仅在价格更优时更新（低吸取更低价，高抛取更高价）。

### 不需要WorkBuddy自动化
此skill完全由本地Python脚本运行，**不需要创建WorkBuddy自动化任务**。通过Windows计划任务自动启停，不消耗token。WorkBuddy自动化(automation-1779181490150)已暂停。

### 计划任务使用PowerShell而非VBS
VBS方式启动Python进程有编码和稳定性问题，改用 `t0_start.ps1`（`Start-Process -WindowStyle Hidden`）更可靠。PS1文件必须用UTF-8 BOM编码保存，否则PowerShell 5.1解析中文会报错。

### 节假日文件需每年更新
`D:\T0交易提醒\data\holidays.txt` 每年1月需根据沪深交易所公告更新。脚本自动跳过配置的节假日日期，避免非交易日浪费资源。

### 标的变更
如需增减监控标的，修改 `D:\T0交易提醒\t0_monitor.py` 中的 `GROUP_A`、`GROUP_B`、`STOCK_NAMES` 和 `ALL_CODES` 变量。

### 科创板说明
科创板（688开头）股票做T+0需要底仓，用户已确认所有科创板标的均有底仓。

### 桌面弹窗
使用PowerShell调用Windows Forms通知，无需安装额外pip包。如弹窗不出现，检查Windows通知设置是否允许。

## 信号文件结构参考

```json
{
  "date": "2026-05-20",
  "stocks": {
    "sz002594": {
      "name": "比亚迪",
      "completedRounds": [
        {"round": 1, "type": "正T", "buyTime": "10:30", "buyPrice": 345.0, "sellTime": "11:15", "sellPrice": 348.5, "spread": 1.01, "netReturn": 0.94}
      ],
      "pendingSignal": null
    }
  },
  "allSignals": [...],
  "completedPairs": [...]
}
```

## 工作流

1. 用户说"启动盯盘"→ 运行脚本
2. 脚本在交易时段每5分钟自动检查
3. 发现信号→声音提醒+桌面弹窗+微信推送（可选）
4. 信号配对→再次提醒确认
5. 15:00→自动生成HTML盈亏日报+浏览器打开
6. 用户可随时Ctrl+C停止

## 踩坑经验

- westock-data CLI返回Markdown表格不是JSON，需用parse_markdown_table()解析
- 字段名映射：change_percent, price, high, low, rsi.rsi_6, macd.macd, mainnetflow, turnover_rate, volume_ratio
- WorkBuddy自动化最小间隔~1小时，无法实现5分钟调度，所以用独立Python脚本
- RRULE FREQ=MINUTELY被拒绝，BYMINUTE多值被忽略
- 同一检查周期需用signaled_codes集合防止同股双向信号自我配对
- PowerShell桌面通知需`-WindowStyle Hidden`和`CREATE_NO_WINDOW`标志，否则会弹黑窗
- PushPlus和Server酱推送走HTTP GET，无需pip依赖，但需注册获取token/key
- VBS `objShell.Run`启动Python后PID获取不可靠，改用Python脚本自写PID文件(`os.getpid()`)更稳
- PowerShell 5.1读UTF-8无BOM文件中文乱码导致解析错误，PS1脚本必须用UTF-8 BOM编码保存
- `$pid`是PowerShell保留变量（当前进程PID），不能用作自定义变量名，需用`$targetPid`等替代
- PowerShell的`catch {}`空块不合法，必须`catch { # comment }`
- Windows计划任务`Start-Process -WindowStyle Hidden`比VBS更可靠地隐藏窗口
