# 回测分析

T+0 盯盘系统的历史回测记录。

## 目录结构

```
回测分析/
├── README.md                    # 本文件
├── T0_strategy_backtest.py      # 回测脚本 v1（基础版）
├── T0_strategy_backtest_v2.py   # 回测脚本 v2（深度分析版：趋势+波动率分组）
└── YYYY-MM-DD-描述/             # 每次回测一个子目录
    ├── README.md                # 本次回测的结论和参数
    ├── data/                    # 原始数据 (JSON)
    │   └── backtest-v2.json
    └── charts/                  # 图表（预留）
```

## 已完成的回测

| 日期 | 描述 | 关键结论 |
|------|------|---------|
| 2026-05-28 | 策略v2回测 | 25%阈值最佳(胜率70.6%)，3条废策略已移除，宁德时代不适T+0 |

## 运行回测

```bash
cd 回测分析
python T0_strategy_backtest_v2.py
```

结果自动保存到 `./YYYY-MM-DD-回测/data/` 目录。
