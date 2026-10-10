# Futu 因子研究看板 V2

本工具是 `SPY_FACTOR_RESEARCH_V1` 的本地只读监控附件。它不会连接账户、查询持仓、发送订单或修改富途策略。

## 一键启动

双击 `START_FACTOR_DASHBOARD.bat`，浏览器打开：

```text
http://127.0.0.1:8766/
```

看板运行时每 2 秒检查一次 `%USERPROFILE%\Downloads\RunLog_*.csv`。文件大小和修改时间连续两次稳定后才读取。关闭服务期间导出的文件会在下次启动时补录。

## 实际流程

1. 将 `factor_research/spy_factor_batch_v1/SPY_SIX_FACTOR_BATCH_V1.py` 完整复制到富途量化编辑器。
2. 手动运行历史回测并导出 `RunLog_*.csv` 到 Downloads。
3. 看板接受单因子 `FUTU_FACTOR_V1|{JSON}` 和六因子
   `FUTU_FACTOR_BATCH_V1|{JSON}`；批次必须完整匹配冻结的 C1 因子目录和定义哈希。
4. 在首页查看项目阶段、下一项工作，以及 15/30/60 分钟因子比较；运行 ID、哈希、导入审计和原始错误保留在“高级资料”。

也可使用网页的“手动选择 CSV”按钮。上传文件保存在本地 `data/inbox/`，不会发送到云端。

## 状态边界

- `VALIDATED` 只代表日志契约、完整性和确定性统计通过，不代表存在可交易 Edge。
- F001 旧版七日日志显示 `FUNCTIONAL_VALIDATION_PASS`，同时保持
  `INSUFFICIENT_EVIDENCE`，绝不等同于 `EDGE_PASS`。
- forward return 是 close-to-close 条件收益，不是实际成交 PnL。
- OOS 未完成时，系统不会自动升级为 `OOS_SUPPORTED`。
- 相同参数和覆盖区间的重复跑次分别存档，但不会合并为独立样本。
- 测试 fixture 默认禁止写入正式数据库。
- 只有计划因子全部登记、所选窗口数据完整、数据资格通过，并且标的、周期、日期范围、研究分区及收益口径一致时才产生正式名次。
- 旧式“在同一 CSV 拼接多个独立 RUN_START”的文件仍会整批拒绝。获批的
  `FUTU_FACTOR_BATCH_V1` 使用一个批次身份和共享事件，在单一 SQLite 事务中展开为六个逻辑跑次；任何目录、版本或事件错误都不会部分导入。

## 可选启动参数

```powershell
py -3.14 -m quant_workflow.factor_research.progress_dashboard --no-browser
py -3.14 -m quant_workflow.factor_research.progress_dashboard --watch-dir C:\path\to\inbox
$env:FUTU_FACTOR_PLANNED_COUNT='6'
```

`FUTU_FACTOR_PLANNED_COUNT` 默认是 C1 计划的 6 个因子；若权威因子目录变更，可在启动前覆盖。默认数据库位于 `progress_dashboard/data/factor_progress_v1.sqlite3`，SQLite 事务保证单个运行的元数据、信号、标签、统计与异常原子更新。
