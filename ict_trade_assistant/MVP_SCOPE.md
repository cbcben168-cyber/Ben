# ICT Trading Desk MVP v0.1

## 授权与边界
本次用户明确要求输出文档后直接实施。唯一开发根目录为 `C:\Users\cbcbe\TradingCodex\ict_trade_assistant`。旧 ICT 项目、历史行情、冻结代码不读取、不修改。无交易账户接口、订单、回测、盈利主张。72 小时是交付窗口，不代表等待 72 小时才交付。

## 交付
- Streamlit + Plotly 单体看板；SQLite 本地持久化。
- 默认 SPY/QQQ/IWM/SOXX，可增删；参数变更保存 old/new 与 UTC 时间。
- 只使用 OpenQuoteContext；报价权限、数据时间、接收时间、Session、来源、延迟明确显示。
- 日线原生；1H/RTH 4H 由完整 RTH 1 分钟数据重建，明确 DERIVED，4H 尾段标为 150 分钟或提前收盘实际时长。
- 前一完整 RTH 高低、独立 PRE/NIGHT 高低、当日完整 5/15/30 分钟 OR。
- 人工区域与失效价格；观察状态与触价事件、人工备注。Sweep/MSS/FVG 仅为人工 SOP 状态，不自动宣称已确认。
- 自动刷新、图层、距离、名单与区域设置；事件去重；重启保留。
- 其他策略、交易记录、期权导航明确 NOT IMPLEMENTED。
- 双击脚本、README、进度和测试、验收记录。

## 数据硬门
交易时钟 America/New_York；exchange_calendars XNYS 提供假日与提前收盘。RTH 开盘 09:30 ET，正常 16:00，提前收盘按日历。2026-10-30 UTC-4，2026-11-02 UTC-5。
Futu ALL 数据按时间拆分 RTH/PRE/AFTER/NIGHT，独立存储；NIGHT 仅表示 Futu 供应商时段，不宣称 Nasdaq 新夜盘已生效。扩展时段假日/提前收盘边界未验证时标 UNKNOWN，不参与关键价。
缺分钟、分页未取全、当前未完成分钟均不得构成完整 OR/聚合柱；当前柱不参与确认。时间经过仅表示本地 nominal close，不证明供应商最终完成；最新两个分钟柱隔离，且供应商最终性仍标 UNVERIFIED。历史结果仅称观测范围，不宣称交易所最终值。
缺实时权限/权限未知为 UNAVAILABLE；时间过旧为 STALE；不填充、不插值、不生成演示行情；历史缓存不转为实时。

## Git 与验证
新独立仓库，分支 codex/ict-desk-mvp-v01；若无远端，完成本地提交并报告 PR 阻断，不猜远端、不推送到旧仓库。验证 DST、假日、提前收盘、完整性、Session、权限/延迟、SQLite 和 UI 启动。真实 OpenD 权限不足时保留可用核心与真实失败证据。

## 完成定义
测试通过、HTTP/UI 可打开与只读接口可执行各自独立记录。实际行情、桌面双击、浏览器视觉验收未验证时不标完成。不得以预留页面或离线测试冒充真实行情验收。
