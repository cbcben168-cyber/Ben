# 10-Min ORB + 3R：固定规则Train研究

用户明确给定且批准的独立策略。允许本候选固定SL/3R的测试，不是对原有尚无edge的策略扫描TP/SL。版本orb10_3r_v1，不修改原有baseline或diagnostic_v2冻结源码/锁，不接账户，不发单。

## 精确规则

- 两根完整5m线09:30–09:35、09:35–09:40 ET建立OR高低与宽度。
- 等待09:40之后的第一根5m收盘严格高于OR高则做多，严格低于OR低则做空；等于边界不算。最后可用信号收盘10:25，10:30严格排除。
- 下根5m开盘进场，内部时间为UTC。前根收盘时间等于下根开盘时间，但价格取新bar开盘，不用信号收盘。该开盘与相同时间的1m开盘必须一致。
- 多头止损OR高−0.25宽度，空头止损OR低+0.25宽度；R=方向×(实际入场价−止损)。目标入场价±3R。R<=0取消当天，不找下一次突破。
- 每天最多一笔；用完整1m路径退出。开盘跳过止损按该分钟实际开盘止损，跳过目标按目标价保守成交；普通1m同时触及SL/TP按SL先发生。精确触及也退出。
- 未触及则当日RTH最后一分钟收盘退出，半日市按XNYS实际收盘。零宽度、无突破、跳过分别有记录。
- 基线往返2bps包含佣金与滑点假设，另报告0/4/8bps，不是实测报价/手续费。不会按结果选择最佳成本。

## 数据与研究边界

复用canonical Futu未复权RTH 1m及同源5m、登记Train日期。先登记本固定规则和输入/source SHA，再计算收益。已有Train baseline被看过，因此是探索研究，不声称Train尚未被使用。Validation/OOS不读取收益、不打开结果。原formal_data_gate仍false，不因为价格策略绕过项目gate。

每个完整Train交易日记录，质量异常整轮失败，不静默剔除、填价。缓存hash校验；已登记/已有结果时拒绝覆盖，失败也保留注册与日志。后续修复须明确新版本并记录尝试，禁止删掉负结果重跑。

只跑该一个固定参数点；无市场状态过滤，无参数扫描，无matched controls/multiple-testing确认。仅输出日期cluster与连续5日block bootstrap各10000次的探索性均值CI，不能单凭区间通过晋级KEEP。主结果合并方向，方向拆分为诊断。

日终NAV以每天1倍名义本金、无交易持现金的示意模型；不是按止损距离固定风险仓位，不包含盘中最大浮亏、融资、借券、限制卖空、借券费或真实订单。Buy & Hold以相同Train首日开盘至末日收盘价格收益扣2bps，包含隔夜、不含分红，暴露与持有时间不同；仅参考，不用于宣称优于同风险基准。

## 命令与产物

在独立项目目录：

```powershell
.venv\Scripts\python.exe -W once::DeprecationWarning -m spy_research.orb10
```

该命令只允许Train首次登记运行；再次运行会提示已有登记，直接阅读原结果。没有paper/shadow接入或自动启动。

- locks/orb10_3r_v1/registry.json：固定规则、日期、来源hash、探索性分类。
- artifacts/orb10_3r_v1/train：daily.csv、trades.csv、quarterly.csv、costs.csv、by_side.csv、summary.json、run_manifest.json、report.md、equity.png。
- logs/orb10_3r_v1：受控失败记录，无凭据/账户/原始异常响应。

判读：扣成本均值<=0为NO_EDGE_TRAIN_SCREEN；正值仍为WEAK_EXPLORATORY。完整数据、样本、匹配对照、稳定性、多重检验与独立确认尚未通过，不输出KEEP或发单授权。
