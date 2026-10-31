# 服务退出与进程生命周期审计

审计日期：2026-10-31（Asia/Shanghai）。此前8501退出根因：**UNRESOLVED**。

## 已有证据

- 本轮开始8501无监听。原runtime.json最后记录PID12548、uptime_seconds=250；旧文件不是当前存活证明。
- 旧stability.log有多次启动指纹、OpenD/VIX历史权限或API失败；旧fatal.log为空；最后stderr只有启动行，没有可归因的退出Traceback。未找到明确服务入口结束记录。
- 查询2026-10-30至本轮检查时的Windows Application事件1000／1001，未返回匹配python／streamlit的记录；System事件41／6008／2004也未返回记录，见windows-event-audit.json。这不是排除系统、人工终止、资源或其他原因的证明。
- 旧报告 `LIVE_ACCEPTANCE.md` 记载过一次备份与重启组合命令被自动审批拒绝。本轮没有重试该命令或处理原PID6316；开始时端口已空，仅在当前用户整体批准后创建本轮服务。未终止其他服务。

以上只能确认旧服务已不在监听，不能把VIX错误、缺少fatal输出或心跳停止等同于退出原因。

## 本轮可复核生命周期

| 操作 | 结果与证据 |
|---|---|
| 正常启动 | 新建8501启动器PID46792／监听子进程34760；健康200、心跳根目录正确；只使用行情接口 |
| 重复启动 | 原Start_ICT_Desk.ps1报告8501占用并退出；原监听进程不变，未另建服务 |
| 双窗口 | 独立Playwright会话两个页面分别选择SPY／QQQ，自动刷新，未提交备注不同；有界检查见browser-soak.jsonl |
| 正常退出 | 自建隔离8505，PID30504，PTY Ctrl+C后端口释放。stability.log记录入口退出及Python正常退出，没有异常结束记录。PTY宿主退出码1不冒充Python异常退出 |
| 异常退出 | 仅对本轮自建8505启动器PID48056执行Stop-Process；其监听子进程47344同时消失、8505释放；无finally退出记录，符合强制终止证据缺口。不能据此反推历史退出原因 |

异常退出前后证据：`data/v03_acceptance/lifecycle-before.json`、`lifecycle-after-launcher-stop.json`、`lifecycle-out.log`、`lifecycle-error.log`。未改动Windows网络、OpenD、其他服务或计划任务。

## 明确缺陷与最小修复

原入口 `except BaseException: log.exception(...)` 把正常SystemExit(0)当成异常。隔离注入已复现 `normal_exit_logged_as_exception=True`；该缺陷会误导日志分类，不能解释历史服务为何退出。

`scripts/run_server.py`将正常SystemExit(0)/KeyboardInterrupt与非零退出／未处理异常分开记录，增加启动PID、端口、正常退出时长及包含入口脚本的代码指纹。仅为隔离验收新增 `--port`；非8501使用独立runtime与fatal文件，避免覆盖主心跳。不增加自动重启或无限恢复。

## 尚未取得的证据

历史强制退出主体、系统资源耗尽、系统重启或Windows终止原因均未确认。长期稳定性结果单独见STABILITY_TEST_RESULTS.md；单次60分钟检查也不能证明隔夜或所有系统状态可靠。

本轮完成3600秒基线监测后关闭独立验收浏览器，8501健康仍200。仅停止本轮自建启动器46792，监听子进程34760随后退出；端口释放存在短暂延迟，保护检查阻止立即重复启动。确认端口释放后原启动脚本正常启动v0.3：启动器38116、监听44052。该人为结束有明确操作链，不冒充历史不明退出的根因证据。
