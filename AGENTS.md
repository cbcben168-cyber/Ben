# 项目目标
构建 TradingView + Python 的历史回测与实时前向测试系统。

# 当前阶段范围
1. 第一阶段只支持 SPY 和 QQQ。
2. 第一阶段只做历史数据下载、EMA 回测、测试和报告。
3. 暂时不接入 TradingView Webhook。
4. 暂时不接入券商。
5. 暂时不自动下单。
6. 暂时不做期权回测。

# 核心规则
1. Python 是确定性计算和数据存储核心。
2. Codex 负责代码开发、运行测试和审查。
3. 不允许由 LLM 直接计算最终交易绩效。
4. 所有时间内部统一使用 UTC。
5. 报告时间可转换为 America/New_York。
6. 禁止未来函数和前视偏差。
7. 信号默认在下一根 K 线成交。
8. 除非明确说明，不允许信号产生当日按同一收盘价成交。
9. 回测必须包含手续费和滑点。
10. 必须检查重复日期、缺失价格和时间排序。
11. 所有策略都必须与 Buy and Hold 对比。
12. 不允许只报告最优参数，必须报告稳定性和样本外结果。

# 安全规则
1. 不得把 API Key、密码或账户资料写入代码。
2. 所有密钥只能放在 .env。
3. .env 必须写入 .gitignore。
4. 当前阶段禁止连接真实交易账户。
5. 当前阶段禁止发送真实订单。

# 开发规则
1. 修改代码后必须运行 pytest。
2. 不得通过删除测试或降低断言标准来让测试通过。
3. 所有收益、回撤、手续费和滑点计算必须有测试。
4. 不得覆盖已有文件，除非任务明确要求。
5. 不得擅自扩大任务范围。
6. 创建文件前先检查当前目录和已有结构。

# 每次任务完成后必须报告
1. 修改了哪些文件。
2. 执行了哪些命令。
3. 测试是否通过。
4. 生成了哪些输出文件。
5. 尚存哪些风险和限制。
## Quant Research Pipeline Entry

- Phase 1 defaults: `optimization_allowed=false`, `fill_timing=next_bar`, and Buy and Hold comparison are mandatory; capability failures remain `STRATEGY_CAPABILITY_BLOCKER` or `DATA_CAPABILITY_BLOCKER`.

- 缁涙牜鏆愰悽鐔稿灇閸滃苯娲栧ù瀣╂崲閸斺€茬喘閸忓牐鐨熼悽?quant-research-pipeline閵?- 姒涙顓婚悽鐔稿灇娑擃厽鏋冮幎銉ユ啞閿涘ptimization_allowed=false閿涘畺ill_timing=next_bar閿涘苯鑻熷В鏃囩窛鐎电懓绨查弽鍥╂畱 Buy and Hold閵?- 濮濓絽绱￠弫鐗堝祦娴兼ê鍘涙担璺ㄦ暏 validated local cache閿涙硩finance 閸欘亞鏁ゆ禍搴㈡绾喗鐖ｇ拋鎵畱 smoke test閵?- 娑撳秵鏁幐浣虹摜閻ｃ儱绻€妞ゆ槒绻戦崶?STRATEGY_CAPABILITY_BLOCKER閿涙稒鏆熼幑顔荤瑝閸欘垳鏁よ箛鍛淬€忔潻鏂挎礀 DATA_CAPABILITY_BLOCKER閵?- 濮濓絽绱＄紒鎾寸亯韫囧懘銆忕紒蹇氱箖 quant-backtest-audit閿涙稑缍嬮崜宥夋▉濞堝吀绗夐懛顏勫З娑撳宕熼妴浣风瑝鏉╃偞甯寸€圭偟娲忕拹锔藉煕閵?
