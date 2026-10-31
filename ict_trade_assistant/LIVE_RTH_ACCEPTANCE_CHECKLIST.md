# 星期一真实RTH只读验收清单

状态：`PENDING_LIVE_ACCEPTANCE`。本轮只准备工具，没有创建后台自动任务、Windows计划任务或未来自动执行承诺。

纽约时区：`America/New_York`。2026-11-02星期一09:30 EST（UTC−05:00）为香港／北京时间22:30（UTC+08:00）；16:00收盘为香港次日05:00。不可沿用上周EDT的21:30开盘时间。

## 使用方法

在项目根目录先运行默认检查（不连接OpenD）：

```powershell
.\.venv\Scripts\python.exe scripts/live_rth_acceptance.py
```

真实RTH由用户手动执行，只读行情，默认5组、间隔30秒，调用耗时另计。最多20组、间隔最多60秒；SDK单次超时仍由现有供应商接口控制，不承诺硬中断API：

```powershell
.\.venv\Scripts\python.exe scripts/live_rth_acceptance.py --capture --samples 5 --interval 30
```

每次生成独立 `data/live_rth_acceptance/时间戳/`，逐组保存 `samples.json`，最后保存 `summary.json`。周末或非RTH即使加--capture也不连接OpenD。不读取账户、不调用订单、不修改用户库；读取设置及五类记录SHA256用于核对。看板同时运行可能产生正常健康／市场事件，差异须逐条解释。

## 逐项验收

| 检查 | 操作与通过标准 | 当前裁定 |
|---|---|---|
| 版本归属 | 确认8501监听PID、data/runtime.json根目录和运行指纹与当前源码一致；旧进程不算新版本验收 | 待现场记录 |
| 四ETF新报价 | SPY、QQQ、IWM、SOXX均有LV1/LV2/LV3、来源和新纽约时间；相邻组quote_at确实推进 | PENDING_LIVE_ACCEPTANCE |
| 90秒门禁 | 报价年龄≤90秒且时钟、权限、交易日均合格才允许LIVE；>90秒必须阻断。不要改阈值制造通过 | PENDING_LIVE_ACCEPTANCE |
| 模式 | 闭市为PREPARATION；真实RTH合格报价为LIVE；RTH断线或过期降为历史／不可用，不沿用旧AVAILABLE | PENDING_LIVE_ACCEPTANCE |
| 候选距离 | 用同一证券同一水平核对新price及gap、ATR距离随新行情变化；历史距离必须明确标历史 | PENDING_LIVE_ACCEPTANCE |
| 证券去重和区域聚合 | Top5按证券最多四ETF，VIX仅背景；闭区间相交含等端点聚合，不修改全部原始价位 | PENDING_LIVE_ACCEPTANCE |
| 自然状态和去重 | 等待自然NEAR/INSIDE/OUTSIDE变化，记录时间和事件ID；两窗口同一数据不重复写市场事件；无变化不新增提醒。若未自然发生则保留PENDING | PENDING_LIVE_ACCEPTANCE |
| 双窗口／备注 | 精确CSS视口2560×1440和1440×2560分别观察SPY/QQQ；启用刷新；未提交输入保持；另用明确测试备注核对保存、重新打开及版本；不覆盖已有备注 | PENDING_LIVE_ACCEPTANCE |
| 断线和有限恢复 | 优先观察自然断线。若需主动操作OpenD／网络或停止其他服务，必须另外确认范围；不得绕过拒绝。核对历史保留标STALE、入场阻断、最多3次、之后需显式手动重试 | PENDING_LIVE_ACCEPTANCE |
| ICT自动提醒 | 保持独立开关关闭。基础行情资格通过不等于ICT实时事件链资格通过；不得仅因离线通过解锁 | PENDING_LIVE_ACCEPTANCE |

## 留证和停止条件

保存采集输出、运行指纹、浏览器检查、用户数据前后比较和人工结论。若权限未知、时间异常、报价过期、数据缺失、SDK故障或未发生自然触价，记录事实并阻断实时操作；不要改历史数据、回放报价或放宽策略条件。

本脚本只采样和输出证据，不能独立证明真实自然触发、UI跨窗口行为、盘中断线或所有提醒去重。所有项目逐项人工裁定，不能因脚本退出码0或存在samples.json便宣称真实盘中验收通过。
