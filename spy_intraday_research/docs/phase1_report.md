# Phase 1 实施与验收报告

日期：2026-10-03。结论：数据基础实现可运行；**整体Phase 1 gate未通过，未进入Phase 2，未执行订单**。

## 实测

- Python 3.12；Futu SDK 10.11.7108；OpenD返回server_ver 1011，行情登录成功。
- 2026-10-02：390根1m（09:31–16:00 ET）、78根5m（09:35–16:00 ET）、1根daily。
- 2023-10-02：同样390/78/1根；只证明该日期可读，不代表完整区间覆盖。
- 实测bar-end时间，修正起点假设后RTH分钟质量通过，无缺口、额外分钟或无效OHLCV。
- 2026-10-02全部78根5m OHLC与1m聚合一致。volume存在78处差异，大部分为1–4股，另有一处69股。首5m的turnover聚合一致，但不能据此推定所有成交量差异来自取整。
- daily OHLC与RTH聚合一致；daily volume为46,335,295，分钟RTH合计39,224,300，口径未解释。
- 保留两次FAILED_DATA运行记录：首轮timestamp假设失败，修正后volume对账失败。没有删除失败结果或调低质量阈值。

## 产物定位

`artifacts/20261003T074320Z_791c00bf`：最近日capability smoke。
`artifacts/20261003T074337Z_00b5264b`：原始采集manifest。
`artifacts/20261003T074414Z_f202944b`：修正后quality、minute/five-minute、daily对账与FAILED_DATA manifest。
`artifacts/20261003T074515Z_4c767421`：2023日期可读性smoke。

所有运行目录本地保留，不提交原始行情。最终测试结果以提交时记录为准。

## 未通过项与后续边界

1. 供应商成交量单位/修订/日线session口径尚未得到充分解释；需只读复取、官方口径核验和更多日期对账，不能放宽gate掩盖问题。
2. 尚未采集完整三年区间、至少500个合格session及daily60日预热；需在数据资格认证后批量采集并报告覆盖与隔离比例。
3. corporate-action来源与分红/拆分标记尚未实施；不允许据现有数据直接进行Gap Fade正式研究。
4. 实时新鲜度、行情权限与bar修订尚未验证；不得启动paper。
5. 父目录Git为空仓库且无remote。已在获批功能分支实施；无法同步不存在的主分支历史、推送或创建PR。未创建任何外部仓库。

参考：[Futu历史K线官方字段与美东时间定义](https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html)。结束时间解释还结合了当前返回的session边界和OHLC聚合证据。

## 最终验证记录

- 16个测试通过：DST、半日市、分钟完整性、OHLC、重复冲突、聚合、未来追加不变性、结束时间转换、分页/权限拒绝、缓存幂等与篡改拒绝、原子写入和订单边界隔离。
- pip check：No broken requirements found。
- 294条依赖弃用警告仍保留，未隐藏成无警告通过。
- 本地Git diff whitespace检查通过。没有远程地址，因此PR状态为NOT_CREATED_NO_REMOTE。
