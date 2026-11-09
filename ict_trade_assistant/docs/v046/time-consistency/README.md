# v0.4.6 部署前最终修订：时间与价格口径一致性

**隔离修复与复验完成；未部署、未重启8506，未合并PR。** 本报告及本目录9文件部署清单取代首轮8文件部署清单。已关闭本轮8526预览及独立浏览器，等待单独部署批准。

本轮基线是用户已审阅的PR #52提交`ba99c7bfac8b263cca9bf8a5c69a0cdb3e408c8d`，继续使用`codex/ict-v046-history-workbench`。最终候选提交的完整SHA随最终回复及PR #52 HEAD给出；部署时须同时匹配该SHA和[9个运行文件的SHA256](deployment-manifest.json)，不能仅使用旧报告的文件清单。

## 根因与最小修复

旧观察卡只显示日K的watch_state.at，却把另算的1H趋势并列显示；1H只要趋势非UNKNOWN就标为合格。主摘要的stale也仅依赖日K日期。因此日K更新到11月9日时，11月6日的旧1H仍可能被误读为同期合格资料。

本轮生产代码仅改`desk/decision_home.py`、`desk/dashboard_cards.py`，新增`desk/history_status.py`：

- 日K、1H各自从已完成计算前缀的at读取真实截止时间，分别显示来源、复权估值日及原精度收盘价。没有用日K日期或估值日补1H空值。
- 最新模式按实际展示时点判断新鲜度，不再把两个周期都裁到日K档案截止日期；回放仍按所选历史时点和原2分钟隔离计算。
- 每个周期独立比较最近完整纽约交易日。旧1H显示“1H历史资料已过期”，不标为“1H合格”；其图形、历史趋势和真实价格保留。主摘要的过期结论使用当前选择的周期。
- 日K/1H估值日不同或缺少统一尺度证据时，主摘要和每张卡片提示“价格尺度未获统一认证”。不跨周期叠加、合并参考价格或计算可执行风险回报；实时交易资格仍关闭。原历史参考函数的分批次保护和人工计划保护保留。
- VEA、IEFA、BND保留原UNAVAILABLE和完整错误原因。没有合格1H记录时显示“无已验收资料”，估值日标明“未提供”，不把未经接受的原始标签或日K日期冒充合格1H元信息。

没有修改行情验证器、`1e-6`价格阈值、冻结指标、EMA/ATR定义、ICT识别器、90秒报价门禁、2分钟隔离、用户计划、既有实验组合或正式8506文件。

## A～F隔离证据

**11月9日日K测试柱为受控合成资料，不是真实OpenD新增日。** 本轮没有访问OpenD或抓取新行情。浏览器测试入口显示合成提示，合成日K来源单独标为`ISOLATED_SYNTHETIC_DAY/QFQ`；1H只读原来已验收的真实归档。

| 项目 | 结果 |
|---|---|
| A／B 日K11月9日、1H11月6日 | 15卡片与主摘要分开显示；有效1H明确过期，未出现1H合格标记 |
| 回放11月6日 | 两周期截止均为11月6日；不按今天判过期，不包含合成11月9日日K |
| C 日K更新保护 | 23只原始1H文件与manifest逐文件SHA256不变；更新前后归档读取元信息、价格帧和校验结果一致 |
| D 不同估值日 | 各自日期、估值日、来源、收盘价保留，统一认证警告可见，执行风险回报为空，交易资格关闭 |
| E 布局 | 2560×1440为5×3；1440×2560为3×5；DPR=1、scale=1、CSS zoom=1；无横向溢出或Python异常 |
| F 原回归 | 从旧验收XML恢复原199个精确pytest节点，原样复跑199通过、0失败、0跳过；旧测试源文件未改 |

新增8项定向测试全部通过；最终来源文字调整后，相关旧测试及新测试共51项再次通过。去重覆盖共207项，不能把重跑次数重复计数。XML：[原199项](original-199.xml)、[新增8项](new-tests.xml)、[最终51项](related-final.xml)；[原199节点清单](original-199-nodeids.txt)。compileall和git diff --check通过。

[浏览器98项检查](browser.json)覆盖真实基线、合成错位、独立周期价格、估值日阻断、三只原始失败、回放和两种布局。初次脚本在截图滚动后操作隐藏的单选输入／下拉选项超时；改为回顶部操作可见标签后完整复跑通过，未放宽产品断言。

截图：

- [真实归档基线15卡](screenshots/baseline-landscape-cards.png)：日K和1H均截至11月6日，估值日分别为11月8日／9日。
- [横屏合成错位主摘要](screenshots/landscape-simulated-main.png)／[横屏15卡](screenshots/landscape-simulated-cards.png)。
- [竖屏合成错位主摘要](screenshots/portrait-simulated-main.png)／[竖屏15卡](screenshots/portrait-simulated-cards.png)。

卡片截图是对应真实浏览器视口中的完整卡片区域裁图；main截图是完整视口。合成图不能用作真实11月9日行情更新或正式部署证据。测试入口没有打开用户计划库，所以这些新截图不含实际用户计划。

## 原始20只与三只拒绝状态

[23只真实归档复核](hourly-audit.json)确认：SPY、QQQ、IWM、SOXX、SMH、VOO、IVV、VTI、VUG、VTV、SPYM、VXUS、IEMG、VGT、GLD、AGG、IWF、IJH、VWO、XLK仍为归档PASS，每只630根；未重抓、未改变OHLC或复权尺度。时间状态属于展示层，不会改写归档的PASS。

原三只仍为UNAVAILABLE，真实原因保持：

| 证券 | 失败原因 |
|---|---|
| VEA | 2026-11-06 QFQ：60分钟汇总与同批日K不一致 |
| IEFA | 2026-11-03 QFQ：60分钟汇总与同批日K不一致 |
| BND | 2026-09-30 QFQ：60分钟汇总与同批日K不一致 |

对应差值与首轮[原始价格差异](../reconciliation-differences.json)相同。`futu_hourly.py`及`futu_daily.py`字节未改；阈值没有放宽。成交量跨周期差异、事后QFQ及供应商最终性限制仍沿用首轮报告，没有宣称解决或新增交易许可。

## 数据和系统保护

[保护报告](protection-final.json)的151项文件检查全部通过，包括正式源码、原日K归档、全部原1H归档文件、旧测试文件和冻结项目模块。用户库schema及全部11张表、实验组合表前后完全一致。[冻结源代码与旧测试哈希](protected-code-sha256.json)保留修改前后依据。

[正式服务进程](services.json)仍为8506 PID63264、8501 PID19544、OpenD PID22236，创建时间早于本轮；两端正式健康检查为200/ok。本轮只启动／停止自己核对身份的8526测试进程，没有调用Windows计划任务接口，没有替换8506文件、修改服务环境或合并PR。[隔离预览停止记录](preview-stopped.json)。

## 最终部署清单与回滚准备（未执行）

正式8506仍为v0.4.5；后续获批时应按本目录[deployment-manifest.json](deployment-manifest.json)部署完整**9个**运行候选文件，不能只复制本轮3个Python文件：

`app.py`、`desk/dashboard_cards.py`、`desk/decision_home.py`、`desk/experiment_ui.py`、`desk/workspace.py`、`desk/futu_hourly.py`、`desk/historical_prices.py`、新增`desk/history_status.py`、`scripts/v04_history_fixture.py`。

1H数据沿用未改变的独立版本归档，目标仍为`data/hourly_history_v046/20261109_ce7fe180`，只增加未来8506进程的`ICT_FUTU_HOURLY_ARCHIVE`指向该目录。现有日K、用户、实验和历史路径环境保留，不触碰PR #51。

部署前应重新核验候选SHA、9文件哈希、当时生产进程身份、用户一致性快照及文件存在状态备份。正式复制、环境设置及8506重启均须另行批准。本轮仅准备清单，没有执行这些操作。

回滚只恢复部署前原有运行文件及环境；新增3个模块仅在其当前哈希匹配候选清单时移出运行范围。保留独立1H数据和证据，不覆盖或回退用户库、实验库、原日K归档及指针；8501、OpenD、计划任务不参与回滚。正式部署前还需以届时的生产状态复核及演练。

## 修改文件、命令和输出

相对ba99c7b的源代码／测试变更只有6个文件：上述2个展示文件、1个新状态辅助，以及`tests/test_v046_time_consistency.py`、`scripts/v046_time_consistency_preview.py`、`scripts/v046_time_consistency_browser.js`。新增本目录证据，根报告增加最终清单入口并刷新其文档哈希。完整清单见[CHANGED_FILES.md](CHANGED_FILES.md)。

Python沿用`C:/Users/cbcbe/TradingCodex/ict_trade_assistant/.venv/Scripts/python.exe`。主要命令：

```text
python .local/time_consistency_protection.py
python .local/run_original_199.py
python -m pytest tests/test_v046_time_consistency.py -q --junitxml=.local/v046-time-consistency/new-tests.xml
python -m pytest tests/test_v046_time_consistency.py tests/test_futu_daily.py tests/test_v0441.py tests/test_experiment_v044.py -q --junitxml=.local/v046-time-consistency/related-final.xml
python .local/time_hourly_audit.py
python -m streamlit run scripts/v046_time_consistency_preview.py --server.headless=true --server.address=127.0.0.1 --server.port=8526 --server.fileWatcherType=none
npx --offline --yes --package @playwright/cli playwright-cli -s=ict-v046-time run-code --filename scripts/v046_time_consistency_browser.js
python .local/time_consistency_protection.py --verify
python -m compileall -q desk/history_status.py desk/decision_home.py desk/dashboard_cards.py scripts/v046_time_consistency_preview.py tests/test_v046_time_consistency.py
git diff --check
```

保护快照、执行日志、旧节点清单及原始输出留在`.local/v046-time-consistency`；可审查JSON/XML和截图保存在本目录，用户数据库不提交。后续只提交并推送到原PR #52，不自动部署或合并。
