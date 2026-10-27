# 本次命令及边界

仅新增 A 的 d2_live_integration；B 和旧研究证据只读。Python统一为 `C:/Users/cbcbe/AppData/Local/Programs/Python/Python314/python.exe`，均带 `-B`。无安装升级、Windows任务修改、交易接口或账户查询。

1. 只读工作树/状态/文档/源码核查；MCP图检索未包含D2-03后使用文件读取。`git fetch origin` 同步远端引用；A有既有未提交文件，未切换/覆盖主分支工作文件。`git switch -c codex/d2-live-integration` 从A已验收HEAD建立分支。PR以同一HEAD的远端 `codex/factor-scout-v1-phase-b-pr` 为base，以免混入A相对默认分支的33个历史提交。
2. 复制D2-03五个必要模块、原POLICY与测试至新目录；增加明确真实分支、Supervisor及入口测试。SDK Adapter、资源评估与Windows Job源码字节一致，原政策不改。未复制旧Run授权。
3. 每轮pytest：`python -B -m pytest -q -p no:cacheprovider --confcutdir=. tests --basetemp=artifacts/<unique> --junitxml=artifacts/<unique>.xml`。定向轮使用tests/test_live_entry.py。所有目录与JUnit独立保留。最初red轮缺少artifacts父目录，且新入口未实现，记录14 setup errors/7 failures；随后21项入口及98项完整回归通过；增加SDK离线解码后106项通过；扩展入口34项通过。中间final轮测试期间源码调整引起内存/磁盘源码不一致，118通过/1失败；未删测试或降低断言。停止修改后最终 `--basetemp=artifacts/sealed_tmp --junitxml=artifacts/sealed_tests.xml`：123 PASS、0 FAIL/ERROR/SKIP，43.53秒。
4. 测试conftest审计钩子禁止socket connect/connect_ex/bind。SDK只做离线解析；测试中的REAL字段仅验证写盘身份在哈希前确定，不能作为真实观察。原生Windows Job强停结果另存FORCED_STOP_ACCEPTANCE.json，自有进程归零。
5. `python -B protect.py` 两次：保护44,065个旧文件，前后变化0。Git管理文件排除（本次明确批准A分支、fetch、提交和PR操作）。B未运行脚本、未写入工作树文件。
6. Python标准库核对sealed_tests.xml、封存新LIVE_CONTRACT/SOURCE_IDENTITY/ENTRY_ACCEPTANCE/ENTRY_SAFETY_STATE。03:31:17北京时间完成，早于03:35。通过新preflight.inspect_once执行独立Job内只读OS元数据，03:31:24结果RESOURCE_ISOLATION_NOT_PROVEN。未进入SDK门。终局写入TERMINAL、live_authorized=false的新单次条件授权、报告与交付Manifest。不重试预检，不延期窗口，不创建采集Attempt。
7. `python -B live_entry.py` 默认输出LIVE_DISABLED；从集成子目录运行`--live`被WRONG_WORKTREE拒绝（无SDK/无Attempt，仅入口拒绝检查）。真实启动必须以A根目录为cwd；本次终局记录还会在授权门拒绝。未调用真实worker。
8. 交付核验：源码身份重算、Manifest SHA256回读、`git diff --check`；仅`git add -- factor_research/d2_live_integration`，提交、推送同名功能分支并创建draft PR。合并不在本次范围。
