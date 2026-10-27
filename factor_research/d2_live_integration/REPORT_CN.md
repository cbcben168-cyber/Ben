# FUTU D2 Live Integration 最终报告

真实入口已补齐并完成离线验收；本次 Live 为 **BLOCKED**，终局停止。

1. 独立真实入口：live_entry.py Supervisor → 自有 Windows Job → worker → collect_live → 固定 SDK Adapter。真实路径不接受 factory 注入；证据在写入和哈希前绑定 REAL_QUOTE_ENGINEERING_OBSERVATION。默认禁止 Live。新合同、源码/SDK/解释器身份、单次条件授权和入口状态分别保存；原 POLICY 字节未改。
2. 测试：最终 pytest **123 PASS / 0 FAIL / 0 ERROR / 0 SKIP**。包含原 D2-03 的77项、SDK原生离线解码回归及38项新入口测试；覆盖身份/授权/窗口/重复Run拒绝、9槽/资源/异常关闭、INVALID与清理、PARTIAL、原生Job强停及自有进程归零。离线测试中的真实模式字段为写盘路径夹具，仅位于测试产物中，不是任何真实行情。
3. Live 未执行的准确原因：03:31:24（北京时间）新鲜预检 **RESOURCE_ISOLATION_NOT_PROVEN**。66个外部候选进程的未来调用未证明隔离；OpenD自动启动的生命周期事件、正在运行的任务用途，以及其他任务时序仍UNKNOWN；连接前配额未验证。本次 engineering_risk_accepted=false，known_conflict=false，proceed_allowed=false。UNKNOWN没有被改成PASS，也没有被断言为已发生冲突。OpenD监听与映像身份已核对；资源门失败后未进入SDK登录/权限门，所以不是OpenD故障。未继承旧Run风险接受或授权。
4. 实际真实逐笔0、盘口0、SDK调用0、TCP探针0；未创建QuoteContext，未开始300秒观察。交叉盘口、积压、行情丢失均为NOT_OBSERVED，不能填零损失。拟定03:35–03:40窗口因门槛失败取消，无延期、无跨日、无重试；未创建采集Attempt目录。
5. 真实原始证据没有生成。工程交付Manifest及文件SHA256可核验；PREFLIGHT、OS快照、原生强停测试、封存JUnit均保留。44,065个冻结文件前后哈希一致。原D2/D2-02/D2-03、失败Run、A4及七天FINALIZED未修改；B未执行脚本且工作树文件未写入。授权Git操作涉及共享管理元数据，保护快照明确排除Git管理文件。
6. 当前不能用于正式订单流因子研究：NOT_QUALIFIED。无新真实样本；不宣称实时资格、绝对UTC资格、物理介质断电持久性或Trading Edge。没有新增D2-05或其他工程任务。

只新增本目录：core/collector为复用逻辑的身份参数与独立真实分支；SDK Adapter、Windows Job与资源评估模块沿用原字节；另有入口、预检、测试及封存文件。SOURCE_ORIGIN.json记录复用身份。执行命令、初期失败和Git方案见COMMANDS.md。
