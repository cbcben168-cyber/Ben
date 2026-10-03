# SPY 日内研究与诊断 Forward Test

独立研究模块；仅连接 Futu quote context，不包含订单或交易账户接口。
完整研究规格见 `docs/spec.md`。当前正式数据质量 gate 未通过；允许Train诊断和明确标记的diagnostic-shadow观察，不允许声称通过edge/OOS或发单。

## 环境与命令

Python 3.12，依赖只安装在本项目 `.venv`。当前主依赖版本见 pyproject.toml，完整快照见 requirements-lock.txt。

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m spy_research.cli doctor --start 2026-10-02 --end 2026-10-02
.venv\Scripts\python.exe -m spy_research.cli ingest --start 2026-10-02 --end 2026-10-02
.venv\Scripts\python.exe -m spy_research.cli validate-data --start 2026-10-02 --end 2026-10-02
```

默认读取 `FUTU_HOST` / `FUTU_PORT`，缺省 localhost:11111；不需要交易密码。配置在 configs/research_v1.json。日期必须是已结束的纽约交易日之前的历史日期。数据、日志和运行产物不进入 Git。

分钟时间戳按实测的 ET bar-end 转换成 UTC 起止；1m 减1分钟，5m减5分钟。XNYS 日历包含半日市与DST。完整session gate采用390/210等动态预期；不插值、不填价格。重复响应幂等，冲突响应失败；分页token或无新数据失败。原始分日CSV与hash sidecar支持恢复，篡改缓存直接拒绝。

validate-data 生成质量/quarantine、1m/5m、native 5m和daily比较、manifest与JSONL日志。OHLC容差0.0001；volume必须一致。当前不同频率的成交量差异没有解释，不放宽gate。daily comparison仅诊断，未完成供应商session口径资格认证。

## 已知限制

- 已采集817个交易日，并实现四setup与统计/诊断forward链路；正式行情执行资格和成交量对账仍未通过。
- 已提供企业行动清单、daily预热和连续覆盖；不同频率成交量的来源差异仍未解释，Phase 1正式数据资格尚未通过。
- 命令以日期分区checkpoint恢复，暂未实现跨进程并发写锁；只支持单进程采集。
- 网络SDK的连接/请求时间由SDK超时机制控制；权限/配额拒绝不重试，临时超时/频率错误最多5次。
- 依赖NumPy 2.5.3与部分pandas timedelta代码产生弃用警告；当前测试通过，尚未做未来版本兼容承诺。
- CLI doctor显示SUCCESS仅表示只读请求成功，不代表research gate通过。FAILED_DATA产物不可进入下游研究。
- 初始本地目录没有remote；现已关联Ben仓库并基于远程默认分支整合。原目录的未跟踪交易脚本未纳入提交。

当前证据及下一步见 docs/phase1_report.md。

每日forward test复盘和用户优化选择规则见 `docs/daily_review_protocol.md`；日报生成器已实现，系统自动启动任务尚未安装。当前运行方式、边界和命令见 `docs/forward_runbook.md`；实施证据见 `docs/forward_implementation_report.md`。

## Gamma 位置研究

新增独立的SPY Gamma 0、Call Wall、Put Wall采集、模型位置、候选买卖点与每日诊断。它不改变现有冻结shadow，不发单；缺历史链不回填，周末报价不给有效信号。运行与限制见 [gamma_levels_runbook.md](docs/gamma_levels_runbook.md)。
