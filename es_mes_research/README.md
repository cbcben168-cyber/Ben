# ES/MES 可选独立研究

默认全部关闭。你可以选择ES、MES、两者、全部关闭；选择只是研究开关，不启动任务、不切换SPY、不下单。脚本scripts/choose.ps1提供0–3菜单，改动只存在本项目state/selection.json。

2026-10-04实测Futu可返回美国期货合约目录，但ES/MES报价和1m历史权限不足。尚无真实历史数据、回测收益、KEEP或forward资格。没有购买数据、账户连接或自动部署。

第一项为用户固定ORB10 + 3R，以09:30 ET现金市场开盘为锚。只用完整XNYS现金RTH窗口；夜间策略/CME全时段日历仍未实现，不把现金窗口当期货全部交易时段。

运行、CSV schema、成本、换月和数据资格见 [docs/runbook.md](docs/runbook.md)。代码独立于SPY项目，不导入或修改它的规则、缓存、冻结文件。新分支codex/es-mes-research，独立PR。
# 网页控制台

运行 `./scripts/dashboard.ps1` 后打开 http://127.0.0.1:8765 。网页可检查行情权限、启动/暂停模拟观察、查看日志、下载每日总结及记录优化选择。详见 [网页说明](docs/dashboard.md)。实时结果是诊断报价代理，尚不具备KEEP资格。
