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
| **策略引擎** | **VWAP锚定 + 多信号共振 v2.0** |
| 检查间隔 | 5分钟 |
| 交易成本 | 佣金万一（双向）+ 印花税万五（卖出单边）= 往返0.07% |
| 单笔仓位 | 底仓的**25%**（保守Kelly系数） |
| 同时开仓 | 最多**2只**股票 |
| 硬止损 | 入场价**-1.5%**无条件止损 |
| 时间止损 | 开仓**30分钟**未盈利即平仓 |
| 连续亏损熔断 | 连续**3笔**亏损当日停止开新仓 |
| 信号冷却 | 同股两次信号至少间隔**20分钟**+价格变动>**1.5%** |

## 日内强制闭环策略（铁律）

**核心原则：底仓不变，T仓日内必须闭环，14:50前所有配对必须完成。**

| 时段 | 阶段 | 策略 | 说明 |
|------|------|------|------|
| 09:30-13:30 | 精选模式 | VWAP共振（A+B+辅助≥3条件） | 严格过滤，质量优先 |
| 13:30-14:30 | 主动寻配 | 有仓位的优先反向信号 | 加速配对 |
| 14:30-14:50 | 强制收尾 | 无条件配对 | ⚡按当前价强制闭环 |
| 14:50 | 硬截止 | 市价强平 | ⚠️所有未配对仓位强制闭环 |

## 新一代策略引擎（v2.0）

### 四层漏斗架构

**第一层：盘前趋势过滤**
- 日线MA20/MA60排列判断趋势：🟢多头 / 🔴空头 / 🟡震荡
- 多头：只做正T（回调低吸），禁用反T防卖飞
- 空头：只做反T（反弹高抛），禁用正T防接刀
- 震荡：正T反T均可，优先配对已有仓位

**第二层：VWAP锚定**
- 日内VWAP（成交量加权均价）= 公允价锚点
- 价格在VWAP附近/下方 → 偏多，找正T机会
- 价格在VWAP附近/上方 → 偏空，找反T机会
- 偏离VWAP>2% → 均值回归机会（需趋势确认）

**第三层：多信号共振入场**
- 必须满足 **A（锚点）+ B（量价）+ 至少1个辅助条件（C~F）**
- C: 趋势一致 | D: 动量背离 | E: 关键位支撑/压力 | F: 时间过滤
- 信号强度1-6星，至少3星才触发

**第四层：风控系统**
- 仓位：底仓25%，最多2笔同时开
- 硬止损-1.5%无条件平仓
- 时间止损30分钟
- 连续亏损3笔熔断

### 入场信号确认表

| # | 确认项 | 正T（低吸）要求 | 反T（高抛）要求 |
|---|--------|----------------|----------------|
| A | **VWAP锚点** | 价格在VWAP附近或下方 | 价格在VWAP附近或上方 |
| B | **量价配合** | 缩量止跌+放量反弹 | 放量滞涨+缩量回落 |
| C | **趋势一致** | 多头/震荡环境 | 空头/震荡环境 |
| D | **动量背离** | 价近低+RSI不新低 | 价近高+RSI不新高 |
| E | **关键位** | ORB下沿/前低支撑 | ORB上沿/前高压力 |
| F | **时间过滤** | 避开开盘噪音+午休 | 同左 |

### 信号输出格式（结构化交易卡片）

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
4. **未完成配对警告**：⚠️ 收盘前未等到配对的首笔信号，标注底仓风险暴露（T仓买入未卖出=底仓多1份；T仓卖出未回补=底仓少1份），系统14:30后强制平仓
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

### 日内强制闭环（铁律）
**底仓不变，T仓日内必须闭环。** 14:30后系统开始强制收尾，14:50硬截止按市价平仓所有未配对仓位。不允许因追求100%胜率而留待匹配交易过夜。

### T+0禁用标的
比亚迪(sz002594)振幅太小不适合做T，已标记为`T0_DISABLED`，仅监控行情不触发信号。

### 防止自我配对
同一检查周期内，同一只股票只触发一个方向信号（低吸或高抛），防止自己跟自己配对。

### westock-data CLI 返回Markdown
CLI输出是Markdown表格而非JSON，脚本内置了 `parse_markdown_table()` 解析器。如果CLI格式变化，需更新解析逻辑。

### 同向信号处理
如果已有未配对信号，再收到同方向信号时：
- 价格更优时更新，但**额外输出"⚠️更优价格"提醒**（非静默更新）
- 低吸取更低价：提醒"可考虑调整止损至XX"
- 高抛取更高价：提醒"可考虑调整回补位至XX"
- 价格未优于已有记录：忽略

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
    "sz300750": {
      "name": "宁德时代",
      "completedRounds": [
        {"round": 1, "type": "正T", "buyTime": "10:30", "buyPrice": 345.0, "sellTime": "11:15", "sellPrice": 348.5, "spread": 1.01, "netReturn": 0.94},
        {"round": 2, "type": "反T", "sellTime": "14:20", "sellPrice": 350.0, "buyTime": "14:45", "buyPrice": 348.0, "spread": 0.57, "netReturn": 0.50, "forceclose": true, "forceclosePhase": "forceclose"}
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
- **Windows后台进程`subprocess.run(capture_output=True, text=True)`的stdout可能为None**：必须显式指定`encoding="utf-8", errors="replace"`并做None防御，否则`.strip()`崩溃
- **收盘日报无法触发**：`is_trading_hours()`在15:00后返回False，`run_check()`直接return，日报代码永远到不了。修复：主循环收盘退出路径直接生成日报，`run_check(force=True)`支持收盘后强制执行
- **"主力流出收窄"条件太松**：原来`abs(net_amount)<500万`就算收窄几乎必触发，改为净流入为正才算"主力净流入"，流出极小需配合股价稳定
- **RSI低吸接飞刀**：RSI6<35单独就触发低吸容易接飞刀（如比亚迪RSI6=25持续一天），改为RSI6<25独立条件，RSI6<35需MACD确认
