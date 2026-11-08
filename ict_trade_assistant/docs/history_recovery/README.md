# ICT Trading Desk 历史日K恢复：隔离开发交付

基线：已验收v0.4.4.1，提交80cece3；开发分支codex/ict-history-recovery。正式8506未修改、未部署。本轮只写独立工作区及其数据库副本。

## 数据与计算结果

23只各90根，合计2070根；纽约交易日2026-07-02至2026-11-06，无缺日、重复、乱序或非法OHLCV。全部来自Futu OpenD的K_DAY / RTH / QFQ请求；同时保存相同区间NONE原始记录及get_rehab完整响应。内部分析时间为UTC；本批共同分析截止2026-11-06T21:02:00Z（纽约16:02）。

以下均由未修改的market_state.py实际计算，不由LLM计算。每只使用最近50根初始化EMA，ATR使用冻结算术均值定义；每只可显示41个合格EMA端点。趋势和波动是历史描述，没有当前交易许可。

| 证券 | 根数／截至 | EMA20 | EMA50 | ATR14 | 趋势 | 波动 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| SPY | 90／11-06 | 759.616537 | 764.136939 | 11.115386 | 过渡 | 高 |
| QQQ | 90／11-06 | 701.186014 | 714.482955 | 16.614036 | 下跌 | 高 |
| IWM | 90／11-06 | 278.109071 | 281.603942 | 4.729286 | 过渡 | 高 |
| SOXX | 90／11-06 | 160.696692 | 168.972956 | 8.615093 | 下跌 | 高 |
| SMH | 90／11-06 | 531.198956 | 553.203649 | 24.639314 | 下跌 | 高 |
| VOO | 90／11-06 | 698.283816 | 702.407833 | 9.766071 | 下跌 | 高 |
| IVV | 90／11-06 | 763.014336 | 767.523115 | 10.725871 | 下跌 | 高 |
| VTI | 90／11-06 | 373.205458 | 375.563911 | 5.135643 | 下跌 | 高 |
| VEA | 90／11-06 | 69.669496 | 70.572917 | 0.937764 | 过渡 | 高 |
| VUG | 90／11-06 | 86.635753 | 88.033755 | 1.890636 | 下跌 | 高 |
| IEFA | 90／11-06 | 96.506227 | 97.428844 | 1.197564 | 过渡 | 高 |
| VTV | 90／11-06 | 225.137524 | 223.661127 | 2.497986 | 过渡 | 高 |
| SPYM | 90／11-06 | 89.411471 | 89.939947 | 1.252486 | 下跌 | 高 |
| BND | 90／11-06 | 70.995029 | 70.852534 | 0.278467 | 上涨 | 正常 |
| VXUS | 90／11-06 | 83.098199 | 84.470461 | 1.108093 | 过渡 | 高 |
| IEMG | 90／11-06 | 75.960961 | 78.509152 | 1.594300 | 下跌 | 高 |
| VGT | 90／11-06 | 118.033673 | 120.492838 | 3.319057 | 下跌 | 高 |
| GLD | 90／11-06 | 372.726247 | 382.476441 | 6.683571 | 过渡 | 正常 |
| AGG | 90／11-06 | 95.672907 | 95.482039 | 0.384611 | 上涨 | 正常 |
| IWF | 90／11-06 | 119.411464 | 121.788905 | 2.758879 | 下跌 | 高 |
| IJH | 90／11-06 | 73.165293 | 73.535762 | 1.156593 | 过渡 | 正常 |
| VWO | 90／11-06 | 56.857731 | 58.337782 | 0.891088 | 下跌 | 高 |
| XLK | 90／11-06 | 181.458575 | 186.004484 | 5.531429 | 下跌 | 高 |

逐只精确值、实验EMA5/35与ATR20对比、校验哈希和复权事件见[真实计算证据](evidence/real-data.json)。Baseline及其原初始化定义不变；用户的现有组合保留。

## 全部23只复权核验

逐根比较QFQ和NONE的OHLCV。现金分红用原始前收盘及分红金额重建，拆股用整数比例重建，同时与供应商有限精度的系数对照。整库复权估值日期统一；不同来源、时段、复权类型或估值日不能拼接。

本批全部OHLC最大绝对误差6.16983129476e-07，低于固定0.000001价格阈值；成交量最大误差5.96046447754e-08。无事件的证券也完成原始/复权逐根一致性检查。算法及字段依据：[Futu官方复权说明](https://openapi.futunn.com/futu-api-doc/quote/get-rehab.html)。

SOXX 2026-11-05的1→3拆股由供应商事件记录确认；SEC公告也已在只读审计阶段核实。11月4日原始收盘450.41、QFQ收盘150.136666516；11月5日收盘131.90。拆股前成交量相应乘3，拆股后不再缩放。

未经处理的NONE收盘变化为-70.7156%，QFQ为-12.1467%；NONE诊断ATR14为43.335995，实际QFQ ATR14为8.615093。没有把机械拆股断层当作市场暴跌，也没有抹去真实行情变动。

QFQ以本次取得时已生效事件回溯调整，属于事后价格口径。历史回放在页面明确提示：它不代表当时实际交易价格，也不是逐时点已知的复权快照，不可据此声称完成无前视的策略回测。

## 独立存储与本机文件清单

数据库：`.local/recovery/futu_qfq_20261106.sqlite3`。数据库及23份原始捕获JSON保留在本机，不提交用户数据库或私有副本到Git。文件大小、逐文件SHA256见[本机数据清单](evidence/local-data-inventory.json)，捕获清单见[vendor manifest](evidence/vendor-manifest.json)。

原始文件：SPY.json、QQQ.json、IWM.json、SOXX.json、SMH.json、VOO.json、IVV.json、VTI.json、VEA.json、VUG.json、IEFA.json、VTV.json、SPYM.json、BND.json、VXUS.json、IEMG.json、VGT.json、GLD.json、AGG.json、IWF.json、IJH.json、VWO.json、XLK.json，位于`.local/recovery/vendor/`；另有`manifest.json`。

SQLite包含独立档案标识、captures、series和bars。完整QFQ/NONE原始记录、复权事件、证券、来源、请求/取得UTC时间、纽约交易日期、SDK版本及哈希均可复核。构造读取器不会创建文件；生产库名称受保护，读取使用mode=ro；导入先验证后在独立事务写入，同日冲突整次拒绝。

23份载荷再次导入：added=0，数据库原始字节完全相同，见[幂等证据](evidence/idempotency.json)。不冒用Alpaca格式，不覆盖原历史JSON、Alpaca归档或v043库。

## 页面及资格边界

原市场答案卡、主图、行动卡、五只固定观察卡及因子区保留。因子区允许最新Futu历史日K、原历史档案和历史日期回放。新来源整批选择，不拼接旧分钟；缺资料时不回退到其他来源。回放只把所选收盘加原有2分钟隔离之前完成的K线交给计算，未来价格投毒检查对23只均不改变结果。

不足50根显示资料不足；不画可靠EMA。新来源没有分钟输入，切换1小时不会生成伪1H或ICT信号。所有新QFQ证券与人工计划价格尺度均未认证，因此原计划保持原价、暂停叠加和风险回报计算；没有自动重算或覆盖计划。

market_state.py、experiment.py、ema_layers.py、analytics.py、ict_v03.py、ict_live_gate.py及90秒/2分钟门禁均未修改。实时资格实际返回false。

## 验证与保护

最终定向pytest：109通过、0失败，覆盖新档案、复权、冲突/幂等、整库估值日、缺资料、回放、页面、旧归档、更新、门禁及部署保护。原有基线25项先行通过；早期两次临时父目录设置错误已修正，未降低测试断言。没有执行全量测试，也不把定向通过当作全量通过。见[测试日志](evidence/targeted-tests.txt)。

生产52个保护文件字节不变，用户SQLite全部11张表的schema和完整内容指纹不变，原实验库也不变。包含名单/设置、计划版本、备注、交易/事件、审计和旧观察记录，见[数据保护报告](evidence/data-protection.json)。

8501、8506、OpenD分别仍为原PID19544、58064、22236；进程创建时间早于本轮预检查，未由本任务重启。8501/8506健康检查均200。四个ICT任务定义逐项一致，日更任务数量0。

**环境审计例外：全系统231个Windows任务中，内置OneSettings/RefreshCache的StartBoundary和Interval在审计期间发生外部变化。全系统任务定义完全不变这一条件未满足；本轮只执行Get/Export任务查询，未注册、修改、启动或恢复任务。不能把项目任务不变写成全部Windows任务不变。**具体前后值与哈希见[运行与任务审计](evidence/runtime-protection.json)。

实际Chrome 156.0.8078.80浏览器269项检查通过，真实页面逐只核验23只各90根及41个EMA端点。2560×1440横屏、1440×2560竖屏均为devicePixelRatio=1、visualViewport.scale=1、CSS zoom=1，侧栏展开，主图与行动卡并排且无横向溢出。完整检查见[浏览器证据](evidence/browser.json)。

截图：[横屏最新SPY](images/landscape-latest-spy.png)、[竖屏最新SPY](images/portrait-latest-spy.png)、[因子对比](images/portrait-factor-comparison.png)、[SOXX 11月4日回放](images/landscape-soxx-replay-1104.png)、[原Alpaca归档SMH](images/landscape-original-smh.png)、[最终页面](images/landscape-final.png)。

早期浏览器驱动先后遇到Plotly二进制数组、日期列表虚拟化、重绘时序和隐藏radio输入的交互问题；均修正驱动的读取/等待/标签点击方式，未调整价格、回放或布局断言。最终完整复验通过。

## 运行命令

在隔离应用目录执行（命令的输出目录须为新的独立路径）：

```powershell
python -B scripts/capture_futu_daily.py --output .local/recovery/vendor
python -B scripts/import_futu_daily.py --capture .local/recovery/vendor --database .local/recovery/futu_qfq_20261106.sqlite3
python -B scripts/verify_futu_daily.py --database .local/recovery/futu_qfq_20261106.sqlite3 --output .local/recovery/final-real-data-evidence.json
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -B -m pytest -q tests/test_futu_daily.py tests/test_v0441.py tests/test_experiment_v044.py tests/test_history_v042.py tests/test_daily_update_v043.py tests/test_decision_first.py tests/test_v04_live_gate.py tests/test_deployment_protection.py
```

预览入口`scripts/history_recovery_preview.py`要求`ICT_HISTORY_RECOVERY_PREVIEW_ROOT`指向当前工作区`.local`内的独立副本，拒绝生产路径；本轮使用8522。捕获和导入是一次性人工工具，未注册无人值守任务。

## 下一步

核对[正式部署清单与回滚方案](DEPLOYMENT_AND_ROLLBACK.md)。本次停止在隔离验收与Draft PR，不执行正式文件替换、用户库写入、8506重启或部署。正式部署须用户另行批准，且必须明确列出首次加载可能追加的观察/系统日志范围。

## 文件修改清单

运行接线：`desk/dashboard_cards.py`、`desk/decision_home.py`、`desk/experiment_ui.py`、`desk/workspace.py`、`scripts/v04_history_fixture.py`；新增`desk/futu_daily.py`。配置只增加根`.gitignore`的`.local/`忽略规则。

新增一次性工具与验收：`scripts/capture_futu_daily.py`、`scripts/import_futu_daily.py`、`scripts/verify_futu_daily.py`、`scripts/history_recovery_preview.py`、`scripts/check_history_recovery_browser.js`、`scripts/check_history_recovery_protection.py`、`tests/test_futu_daily.py`，以及本交付目录内的报告、脱敏证据和截图。

隔离预览8522和本轮独立浏览器已在验收后停止；8501/8506健康仍为200。正式六文件与冻结文件的本轮字节清单见[运行文件清单](evidence/runtime-file-manifest.json)。
