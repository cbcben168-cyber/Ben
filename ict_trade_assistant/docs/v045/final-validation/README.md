# v0.4.5 正式部署前最后验证（2026-11-09）

真实OpenD更新、更新任务生命周期、页面测试稳定性均为 **PASS**。本次停止在隔离验收，未部署8506，未注册或修改Windows任务，未连接交易账户。

## 真实OpenD获取

通过 `start_update → scripts/update_futu_daily.py → worker → scripts/capture_futu_daily.py` 实际执行两次完整更新。SDK **10.12.7208**；本地 `127.0.0.1:11111`；每次23只证券全部取得QFQ、NONE及get_rehab。每个价格序列以50根分页，实际返回50+40两页，共92个日K分页请求、23个复权事件请求。23只各90根、总2070根、2026-07-02至2026-11-06，全部通过现有来源、连续性、价格、成交量和独立复权验证。

两次均 `UP_TO_DATE`：全部价格、原始价格、SDK版本和复权事件相同，0新增交易日；未创建current.json或新数据库，基线SHA256保持不变。仅取得时间或检查日期改变不会制造新版本，旧归档保持原复权估值日期；有实际数据或复权事件变化时仍重新验证并创建独立版本。没有跨供应商或跨估值日期拼接。

[live-opend.json](live-opend.json)保存两次每个原始捕获文件SHA256、manifest SHA256、SDK版本、逐页返回数量及时间、逐证券复权检查误差。完整原始JSON、manifest、任务日志和结果回执保留在本工作树 `.local/final-validation/live/versions/capture_<token>/` 及同级 `task_<token>.log`；不提交私有数据库。超时和故障测试使用受控故障注入，与真实抓取成功证据分别标记。

## 最小生命周期修复

- 用OS持有的字节锁替换PID探活。Windows PID复用不参与任务所有权判断；持锁进程存在时不清理任务标记，进程退出后OS自动释放锁。`update.guard`永久保留，文件存在不表示有活动任务。
- 独立监督进程用Windows Job Object持有工作进程及其后代。工作进程等监督进程建立归属后才执行；600秒限制完整抓取、校验、发布和清理。到期关闭整个进程树，最多再等待10秒回收，不按裸PID终止其他进程。
- 快速两次点击只创建一次任务；启动保留期15秒，损坏或异常退出的任务记录在取得OS锁后恢复。失败可重新执行。总超时报告当前阶段，抓取异常报告退出码并保留日志。
- 原子发布指针同时携带发布结果，独立任务回执作为状态写入失败的恢复来源。发布后写状态失败不会回报成未发布或撤销已发布数据。页面显示恢复结果与状态写入警告。

## 页面卡住的复现结论

`test_home_futu_source_comparison_replay_and_plan_scale_block`没有修改、删除或跳过。旧基线d495bd8和PR #50在受限沙箱中均卡在Windows asyncio创建socketpair时的`socket.accept`，早于页面脚本执行；分别受控终止于45秒和100秒，堆栈见[原基线](page-baseline-sandbox.txt)、[PR #50](page-current.txt)。在允许本地socketpair的相同Python环境中，原基线4.06秒通过，新版3.76秒通过；最终整套定向测试也包含此用例并通过。这是执行环境限制的复现证据，不归因于更新功能。

## 最终隔离验收

最终定向pytest **48通过、0失败、0跳过**，含原页面用例、发布与回滚、缺失数据、真实工作进程树超时、校验阶段挂起、实际抓取子进程退出、快速点击、陈旧/损坏标记、状态文件写入失败、失败重试、EMA/ATR、回放截断和ICT实时资格锁。之后退出码中文报告细化的2个相关用例再次通过。完整结果见[pytest-final.xml](pytest-final.xml)。

在8524隔离服务的同一浏览器页面，无重启/手动刷新，用受控合成快照发布完整23只版本：截至日期2026-04-09 → 2026-04-10，SPY EMA20 156.570454 → 157.570454、ATR14 3.000000 → 3.357143；页面无异常，实时ICT仍关闭。见[cache-refresh.json](cache-refresh.json)。这部分是历史模拟验收，不是本次OpenD新增交易日。

[protection.json](protection.json)核对隔离用户副本的全部计划版本、设置/观察名单、备注、审计、确认及实验组合，与原副本逐行一致；8个冻结计算/ICT/计划模块与d495bd8内容和哈希一致。正式8506用户库、指针及启动配置未被本次验证打开或修改。8524预览已停止。

## 本轮准确修改范围

运行代码：`desk/futu_update.py`、新增`desk/futu_task.py`、`desk/futu_update_ui.py`、`scripts/capture_futu_daily.py`、`scripts/update_futu_daily.py`。

测试：`tests/test_futu_update_v045.py`、新增`tests/test_futu_task_lifecycle.py`。原卡住页面测试保持原样。

交付：`docs/v045/README.md`及本目录README、summary.json、live-opend.json、protection.json、cache-refresh.json、pytest-final.xml、两份沙箱堆栈日志、evidence-sha256.json。

## 正式部署范围和剩余风险

正式部署须单独批准，再备份并核对正式8506身份及源码。完整v0.4.5运行文件沿用PR #50部署清单，加上新的`desk/futu_task.py`；仅配置8506专属独立版本目录并保留原基线、用户库与实验库路径。部署不需要新增依赖、注册Windows任务或改变冻结ICT规则。只对获批的8506执行受控切换，8501及OpenD保持原服务。

当前本地OpenD连接、权限和SDK分页已验证；未来权限或供应商行为变化仍会失败关闭。下一个真实完成交易日尚未发生，真实新增日的最终性只能届时验证。全盘不可写时无法保证写入中文错误文件；若指针已提交，页面可从指针恢复成功结果，既有归档仍可只读访问。原始捕获按任务保留，需要运维留意版本目录磁盘空间。

主要执行命令：`pytest -q tests/test_futu_daily.py tests/test_futu_update_v045.py tests/test_futu_task_lifecycle.py tests/test_v04_live_gate.py --junitxml=...`、原基线同名页面用例、`compileall`、`git diff --check`；真实更新由本机隔离验收脚本调用新版入口，两次任务token与原始文件哈希见live-opend.json。随后提交并推送现有独立分支，更新Draft PR #50；不合并、不部署。
