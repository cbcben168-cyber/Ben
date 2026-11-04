# RTH运行恢复与审计修复（2026-11-04）

【当前阶段】已证实运行阻断的定向修复与工程验证完成；尚不具备重新注册整场无人值守任务的条件。

【执行状态】`ENGINEERING_VERIFIED / UNATTENDED_CONDITIONS_BLOCKED`。没有新增计划任务，没有开启实时ICT。以下时间均为香港时间，代码版本为`RTH_RECOVERY_V3_20261104`。

## 已完成与实际证据

| 项目 | 结果与边界 |
|---|---|
| 8501恢复 | 11月4日19:12左右使用既有`scripts/run_server.py`受控启动；监听PID19544，父进程45576；HTTP200，产品目录与冻结构建指纹一致 |
| 短时稳定性 | 末次工程检查进程运行310秒，仍为同一PID、HTTP200；未执行60分钟或其他无关长测试 |
| 独立OpenD诊断 | 在8501启动前进行；行情worker PID45580，行情已登录，LV3，响应约1.922秒，服务器时差约-2.621秒；不查询交易账户、持仓或订单 |
| SDK阶段 | 已保存SDK_IMPORT、SDK_INITIALIZING、GLOBAL_STATE_REQUEST、PERMISSION_REQUEST、RESPONSE_COMPLETE及请求ID/PID/时间 |
| 页面工程检查 | 150秒有界双窗口检查退出0；18条检查全部通过，SPY横屏2560×1440与QQQ竖屏1440×2560均证明自动刷新；页面异常0、ICT开关违规0 |
| 真实RTH证据 | 本轮不补采历史行情、不重跑正式RTH；上述诊断及页面检查不授予真实RTH通过 |
| 定向测试 | 旧v2复现4个失败；修复版11项通过、0失败，另有4条既有依赖弃用警告 |

冻结v0.3仍为`92ce0a2f8c371dbea742ac2c5c92228be72d53e0`，构建指纹为`19d76ebe4792b5ce894f9826e338b752dd05d3d8416500798ef30ac40e9ea329`。产品、ICT规则、90秒门禁及两分钟隔离均未修改。

## 修复内容

- 新增独立v3控制器，复用未修改的v2有界SDK子进程。8501失败时仍执行独立preflight，并标记`INDEPENDENT_DIAGNOSTIC_ONLY`；仅生产服务身份通过后的同期报价才能进入生产LIVE判断。
- 直接请求Windows `TCP_TABLE_OWNER_PID_LISTENER`表确认监听及PID，不再依赖`Get-NetTCPConnection -State Listen`过滤。本机已观测到监听表成员的原始State为0，原过滤可能丢失实际监听行。监听表成员仍须通过PID、父进程、冻结指纹、根目录、心跳及HTTP检查；没有放宽身份门禁。
- 恢复冷却比较使用明确的1毫秒容差，避免微秒抖动跳过五分钟周期；60秒/300秒恢复周期保持。
- 102个计划点逐个进入coverage；睡眠或时间跳跃漏过的点记录NOT_EXECUTED，实际采样时间为空，不回填历史LIVE。生命周期保存启动PID、开始时间、最后采样完成时间、结束时间及LATE_FINALIZED。
- 版本与端口PASS必须有成功身份/健康检查；OpenD连接PASS必须对应真实worker请求ID和阶段文件；双窗口PASS必须有同期SPY和QQQ成功检查。文件清单按实际存在的文件生成。
- 浏览器在服务恢复后的受控检查中才启动；没有页面证据时保持BLOCKED/NOT_OBSERVED。所有未知服务仍FAIL_CLOSED，不终止未知PID。

## 对20261103原结果的独立重审

原`data/live_rth_acceptance/20261103/`全部原样保存。重审另存：

`data/rth_recovery_v3/20261104/corrected-20261103/`

| 项目 | 修正裁决 |
|---|---|
| 计划覆盖 | 102/102已分类；69次原实际尝试、33个NOT_EXECUTED |
| 版本与端口 | BLOCKED，撤销原无成功检查的PASS |
| 独立OpenD连接 | NOT_OBSERVED，原worker为0 |
| RTH报价 | BLOCKED，合格样本0 |
| 双窗口 | BLOCKED，无原浏览器证据 |
| 报告时效 | LATE_FINALIZED，原报告约08:52完成，超过05:10 |
| 分钟契约与ICT | BLOCKED，TIME_CONTRACT_UNRESOLVED，UNKNOWN、提醒关闭 |

该重审只解释已有真实记录，不重现交易时段、不补造SDK或浏览器证据。当前发现的State枚举异常不能倒推原时段实际监听情况；原记录缺少原生TCP/PID证据，不能补证。原进程旧心跳及Windows重启证据仍分别保留。

## 无人值守条件

Windows当前为China Standard Time（UTC+8），正式观察仍使用America/New_York和XNYS。当前用户处于登录会话，原任务为Interactive/Limited；退出登录、断电及睡眠均可能阻断。

系统自动睡眠超时为0，但唤醒定时器禁用。原任务WakeToRun=true不能代替系统唤醒条件。Windows Power-Troubleshooter事件1记录11月4日02:26:19左右睡眠、08:52:00恢复；睡眠原因另见Kernel-Power的Application API记录。未修改电源、安全、登录或时间服务配置。读取活动wake timers需要管理员权限，当前未提权，具体活动定时器保持未知。

因此目前**不满足无人值守整场正式验收前置条件**；本轮没有注册新任务。代码只能在唤醒后真实记录时间缺口及LATE_FINALIZED，不能保证睡眠期间采集或按截止时间落盘。

## 最小测试与保护核对

测试覆盖：8501缺失仍诊断、服务恢复后检查恢复、睡眠跳跃不回填、102点完整分类、缺证据不PASS、微秒边界、监听表State为0、OpenD无阶段文件拒绝PASS、原69/33重审、未知PID关闭生产资格、用户表及旧报告保护。

证据目录：`data/rth_recovery_v3/20261104/`。主要文件：

- `red.xml`：旧v2定向复现，4失败、2通过。
- `tests-final.xml`：修复版11通过。
- `independent-opend/diagnostic.json`、`workers/1/phases.jsonl`：本轮真实只读诊断。
- `service-restore/service-identity.json`、`service-check-final.json`：真实PID、路径、指纹和短时持续运行。
- `browser-smoke/browser.jsonl`、18张截图、DOM及`exit.json`：当前页面工程检查，不是RTH验收。
- `preservation-before.json`、`preservation-after.json`：原报告/冻结脚本哈希与五张用户表保护。
- `task-readback.json`：原任务仍为Ready，LastTaskResult=2，NextRun为空。

原报告和冻结脚本哈希保持；五张用户表（备注、计划版本、设置、确认、审计）指纹保持。实际页面刷新按原产品行为更新行情缓存/系统记录，SQLite字节发生变化，不声称整库字节不变。未覆盖、恢复或手工写入用户SQLite。v0.4工作树的42个代码文件哈希保持，本轮未启动/停止/操作8506；其他并行工作引起的运行PID变化不能归为本轮成果。

## Git与回滚

生产工作树保持冻结HEAD。修复分支为`codex/rth-runtime-audit-repair`，发布工作树为`ict_trade_assistant_rth_repair`，从远端默认分支`codex/forward-factor-signal-design`同步创建。PR仅新增`ict_trade_assistant/`下的独立验收代码、定向测试及本文；原v2依赖按原哈希归档供审阅，不修改任何冻结研究文件。没有合并PR#38/#39或其他PR。

回滚不需修改生产HEAD：停止使用新v3验收入口，保留原v2及所有证据。看板仍运行原冻结入口。本轮没有新增自动任务需要取消。需要撤销代码发布时仅撤销本修复分支提交，不重置共享远端或其他工作树。

【剩余问题】唤醒/电源运行条件未保证；新的真实RTH、自然触价/恢复及提醒去重未取得；分钟标签契约仍未解决，实时ICT资格继续关闭。

【下一步】停止开发。先解决或明确接受整场保持唤醒/登录的运行条件，再另行安排一次真实RTH；不能因工程测试或独立探针通过自动注册整场任务。
