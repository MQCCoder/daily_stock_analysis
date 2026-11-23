#!/usr/bin/env python3
"""Isolated, one-request stock research experiment. No existing app configuration is loaded."""
import datetime as dt
import json
import os
from pathlib import Path

import litellm
import tiktoken
import yfinance as yf

MODEL = "openai/gpt-4o-mini"
BASE_URL = "https://api.openai.com/v1"
TICKER = "300308.SZ"
MAX_INPUT_TOKENS = 3000
MAX_OUTPUT_TOKENS = 700
# Conservative planning rates, not actual API prices or a guaranteed billing ceiling.
PLANNING_INPUT_USD_PER_M = 2.0
PLANNING_OUTPUT_USD_PER_M = 8.0
DEFAULT_RUN_BUDGET_USD = 0.02
REPORT_DIR = Path("artifacts/openai-stock-test")


def preflight(prompt_tokens: int, budget_usd: float) -> float:
    if prompt_tokens <= 0 or prompt_tokens > MAX_INPUT_TOKENS:
        raise RuntimeError(f"Preflight blocked: input tokens={prompt_tokens}, limit={MAX_INPUT_TOKENS}")
    if not 0 < budget_usd <= DEFAULT_RUN_BUDGET_USD:
        raise RuntimeError(f"Preflight blocked: budget must be (0, {DEFAULT_RUN_BUDGET_USD}]")
    projected = (prompt_tokens * PLANNING_INPUT_USD_PER_M +
                 MAX_OUTPUT_TOKENS * PLANNING_OUTPUT_USD_PER_M) / 1_000_000
    if projected > budget_usd:
        raise RuntimeError(f"Preflight blocked: projected ${projected:.6f} > ${budget_usd:.6f}")
    return projected


def fetch_market_context() -> dict:
    """Get daily bars; fail closed if source unavailable or stale (no fabricated prices)."""
    bars = yf.Ticker(TICKER).history(period="3mo", interval="1d", auto_adjust=False)
    if bars.empty or len(bars) < 25:
        raise RuntimeError("Missing or insufficient daily market data; no model call made")
    bars = bars.dropna(subset=["Close", "High", "Low", "Volume"]).copy()
    if len(bars) < 25:
        raise RuntimeError("Insufficient valid daily market data; no model call made")
    last_day = bars.index[-1].date()
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    if last_day > today or (today - last_day).days > 7:
        raise RuntimeError(f"Stale or invalid market date {last_day}; no model call made")
    c = bars["Close"].astype(float)
    low9, high9 = bars["Low"].rolling(9).min(), bars["High"].rolling(9).max()
    rsv = (c - low9) / (high9 - low9).replace(0, float("nan")) * 100
    k = rsv.fillna(50).ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    dif = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    latest = bars.iloc[-1]
    return {
        "stock": "中际旭创", "ticker": TICKER, "currency": "CNY",
        "source": "Yahoo Finance via yfinance (delayed daily OHLCV; not real-time)",
        "as_of_trading_day": str(last_day),
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "last_close": round(float(latest["Close"]), 3),
        "last_volume": int(latest["Volume"]),
        "ma5": round(float(c.tail(5).mean()), 3),
        "ma10": round(float(c.tail(10).mean()), 3),
        "ma20": round(float(c.tail(20).mean()), 3),
        "macd_dif": round(float(dif.iloc[-1]), 4),
        "macd_dea": round(float(dea.iloc[-1]), 4),
        "kdj_k": round(float(k.iloc[-1]), 3),
        "kdj_d": round(float(d.iloc[-1]), 3),
        "kdj_j": round(float(3*k.iloc[-1] - 2*d.iloc[-1]), 3),
        "last_10_closes": [round(float(v), 3) for v in c.tail(10).tolist()],
    }


def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Missing OPENAI_API_KEY GitHub Actions secret")
    if any(os.getenv(k) for k in ("AIHUBMIX_KEY", "GEMINI_API_KEY", "LLM_CHANNELS", "LITELLM_CONFIG")):
        raise RuntimeError("Isolation failed: external provider/router variables present")

    market = fetch_market_context()
    system = ("你是谨慎的A股研究分析员。仅基于提供的行情快照，使用中文报告。"
              "明确数据日期与数据延迟。禁止声称获取了实时新闻、资金流、订单或买卖盘。"
              "区分观察事实、条件推演和不确定性。不是投资建议。")
    prompt = ("请对中际旭创（300308.SZ）生成简洁的日线技术分析：MA5/10/20、MACD、KDJ、"
              "可能的支撑压力观察条件、上涨与下跌两种情景、数据限制；不得编造实时价格。\n"
              "以下是结构化行情快照：\n" + json.dumps(market, ensure_ascii=False, separators=(",", ":")))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    encoder = tiktoken.encoding_for_model("gpt-4o-mini")
    estimated_tokens = sum(len(encoder.encode(m["content"])) for m in messages) + 64
    run_budget = float(os.getenv("OPENAI_TEST_MAX_USD", str(DEFAULT_RUN_BUDGET_USD)))
    projected = preflight(estimated_tokens, run_budget)

    litellm.num_retries = 0
    response = litellm.completion(
        model=MODEL,
        api_key=os.environ["OPENAI_API_KEY"],
        api_base=BASE_URL,
        messages=messages,
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.2,
        timeout=30,
        num_retries=0,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise RuntimeError("Empty model response")
    usage = response.usage
    prompt_used = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_used = int(getattr(usage, "completion_tokens", 0) or 0)
    if prompt_used <= 0 or output_used <= 0:
        raise RuntimeError("Missing model token usage; cannot validate API costs")
    if output_used > MAX_OUTPUT_TOKENS:
        raise RuntimeError("Unexpected output token count")
    try:
        model_estimated_cost = float(litellm.completion_cost(completion_response=response, model=MODEL))
    except Exception:
        model_estimated_cost = None
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = ("# 中际旭创｜OpenAI 隔离单股验证报告\n\n"
              f"数据来源：{market['source']}\n\n"
              f"行情日期：{market['as_of_trading_day']}（非实时）\n\n"
              f"调用路由：{MODEL} → {BASE_URL}\n\n"
              + content + "\n")
    (REPORT_DIR / "report.md").write_text(report, encoding="utf-8")
    cost_data = {
        "model": MODEL, "api_base": BASE_URL, "ticker": TICKER,
        "as_of_trading_day": market["as_of_trading_day"],
        "preflight_token_estimate": estimated_tokens,
        "preflight_conservative_estimated_usd": round(projected, 8),
        "prompt_tokens": prompt_used, "completion_tokens": output_used,
        "estimated_api_cost_usd": model_estimated_cost,
        "per_run_local_budget_usd": run_budget,
        "note": "Estimates are not an account billing statement or a guaranteed financial cap; monthly usage must be checked in OpenAI Platform.",
    }
    (REPORT_DIR / "usage.json").write_text(json.dumps(cost_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ROUTE={MODEL} BASE_URL={BASE_URL} STOCK={TICKER}")
    print(f"USAGE input={prompt_used} output={output_used} estimated_usd={model_estimated_cost}")
    print("ISOLATED_STOCK_TEST_PASSED")


if __name__ == "__main__":
    main()
