# Futu Quant 因子研究进度看板 V1

本工具是 `SPY_FACTOR_RESEARCH_V1` 的本地只读监控附件。它不会连接账户、查询持仓、发送订单或修改富途策略。

## 一键启动

双击 `START_FACTOR_DASHBOARD.bat`，浏览器打开：

```text
http://127.0.0.1:8766/
```

看板运行时每 2 秒检查一次 `%USERPROFILE%\Downloads\RunLog_*.csv`。文件大小和修改时间连续两次稳定后才读取。关闭服务期间导出的文件会在下次启动时补录。

## 实际流程

1. 将 `factor_research/spy_factor_v1/SPY_FACTOR_RESEARCH_V1.py` 完整复制到富途量化编辑器。
2. 手动运行历史回测并导出 `RunLog_*.csv` 到 Downloads。
3. 看板只接受 `FUTU_FACTOR_V1|{JSON}` 日志；旧探针会显示为“忽略/非因子日志”。
4. 在网页查看 F001、每次运行、15/30/60 分钟统计、数据门槛和异常。

也可使用网页的“手动选择 CSV”按钮。上传文件保存在本地 `data/inbox/`，不会发送到云端。

## 状态边界

- `VALIDATED` 只代表日志契约、完整性和确定性统计通过，不代表存在可交易 Edge。
- forward return 是 close-to-close 条件收益，不是实际成交 PnL。
- OOS 未完成时，系统不会自动升级为 `OOS_SUPPORTED`。
- 相同参数和覆盖区间的重复跑次分别存档，但不会合并为独立样本。
- 测试 fixture 默认禁止写入正式数据库。

## 可选启动参数

```powershell
py -3.14 -m quant_workflow.factor_research.progress_dashboard --no-browser
py -3.14 -m quant_workflow.factor_research.progress_dashboard --watch-dir C:\path\to\inbox
```

默认数据库位于 `progress_dashboard/data/factor_progress_v1.sqlite3`，SQLite 事务保证运行元数据、信号、标签、统计与异常原子更新。
