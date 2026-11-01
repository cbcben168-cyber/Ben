# v0.4 决策辅助工作流实施计划

日期：2026-11-01。授权：本轮首次批准覆盖P0–P6；不含合并、生产部署、账户连接或未来任务。

## 范围与隔离

- 原目录 `C:/Users/cbcbe/TradingCodex/ict_trade_assistant` 保留在v0.3提交 `92ce0a2`，8501不覆盖。
- 开发工作树 `C:/Users/cbcbe/TradingCodex/ict_trade_assistant_v04`，分支 `codex/ict-v04-decision-workflow`。
- 原库通过SQLite只读连接执行一致性备份，保存到开发树 `data/v04_acceptance/v03-user-backup.sqlite3`；绝不恢复覆盖原库。
- v0.4默认新库 `data/v04/desk.sqlite3`，浏览器验收库 `data/v04_acceptance/browser.sqlite3`，默认端口8506。
- 原未跟踪文件、冻结识别器、RTH清单、研究文件及冻结参数保留；不进行Edge研究。

## 实施顺序及可验证标准

1. P0：Git、源码原始SHA256、用户表指纹、原未跟踪文件指纹；重跑95项v0.3基线测试。
2. P1/P2：新增纯函数决策层，复用v0.3事件；固定排序、关联链审查、下一条件与期限，不重新发明识别条件。
3. P3：复用计划JSON版本、乐观并发检查和事件事务，附加人工证据及决策快照；价格提醒沿用LIVE门禁，ICT实时提醒关闭。
4. P4：保持原CSS和默认1H，将相同事件报告传给图层与决策卡；保留首页持仓占位、计划和提醒。
5. P5：单元回归、已有真实历史前缀、坐标核对、双窗口刷新及独立有界稳定性、数据保护与账户接口检查。
6. P6：本地提交及远端草稿PR，保留v0.3回滚路径，不合并、不部署。

## 远端目录差异

远端无main/master；#38以 `codex/forward-factor-signal-design` 为基线，头分支 `codex/ict-desk-v03-weekend` 是多项目树，ICT位于 `ict_trade_assistant/`。本地仓库是ICT根目录树。发布必须在远端原树上只更新对应ICT文件，不能把本地根目录直接作为远端PR树，以免删除其他项目。新增v0.4草稿PR以#38头分支为比较基线；#38保持不合并。远端发布分支使用 `codex/ict-v04-decision-workflow-pr`。

## 验收边界

真实历史为既有7条Sweep、27个独立FVG，合格真实完整MSS链为零。完整链仅用明确标记的合成样本验证。供应商最终性、历史逐分钟PIT和真实RTH不由离线结果证明。2026-11-02 09:30 EST为香港22:30，仍使用冻结v0.3及原清单；不创建未来任务。
