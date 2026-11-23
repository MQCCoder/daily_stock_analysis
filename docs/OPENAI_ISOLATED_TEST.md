# OpenAI Pro API：隔离股票测试

## 仓库现状

- 现有 `.github/workflows/daily_analysis.yml` 的正式定时任务保持原样。
- `src/config.py` 在未指定主模型时可能根据 `GEMINI_API_KEY` 优先选择 Gemini；旧配置中 `AIHUBMIX_KEY` 优先于 `OPENAI_API_KEY`。多渠道或 YAML 配置也能改变路由。
- 因此这个独立测试不加载项目配置文件，不调用主流程，而是在脚本中固定 `openai/gpt-4o-mini`、官方 URL、唯一的 `OPENAI_API_KEY`。

## 手动运行

1. 确认仓库 Repository secrets 中存在 `OPENAI_API_KEY`，并属于 Personal 组织。
2. 本 PR 先保持为草稿。工作流需合入默认分支才能从 GitHub Actions 页手动启动。
3. 审核合并后，进入 Actions → OpenAI Isolated Stock Analysis (manual only) → Run workflow。
4. 成功日志打印 `ROUTE=openai/gpt-4o-mini BASE_URL=https://api.openai.com/v1 STOCK=300308.SZ` 和 `ISOLATED_STOCK_TEST_PASSED`。
5. 下载 artifact 查看 `report.md` 和 `usage.json`，并在 OpenAI Platform Usage / Credit Grants 核对扣费。
6. 数据来自 Yahoo Finance 日线，可能滞后；超过7天或数据不足则在模型调用前失败，不捏造价格。

## 成本保护与限制

- 每次只分析中际旭创一只股票；输入最多3000 tokens，输出最多700 tokens。
- 按规划的2 USD/百万输入 tokens、8 USD/百万输出 tokens进行前置估算，目标单次预算不超过 0.02 USD。该估算并非实际官方价格或硬性账单封顶。
- 不配置定时触发、不重试、不自动 fallback、不修改原有模型密钥与 Codex 登录。
- `usage.json` 记录本次实际 token 和 LiteLLM 推算费用，**不等于月度实际账单**；月度累计预算熔断还未实现。
- 请在 API Platform 配置预算告警并检查余额、自动充值设置。

## 正式主工作流接入门槛

确认单股报告可信、实际模型走 OpenAI 官方、Token统计正常、Usage发生费用记录后，再另开PR改动主工作流，加入持久化预算账本和复盘指标。
