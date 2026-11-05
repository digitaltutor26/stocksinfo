import json

from openai import OpenAI

from config import OPENROUTER_API_KEY

# The OpenAI SDK raises at construction time if api_key is empty/None (not
# just when it's actually used) — so merely *importing* this module without
# OPENROUTER_API_KEY set would crash, regardless of whether anything ever
# calls out to OpenRouter. That's exactly what happened in CI: pytest
# collection imports every test file before any fixture (including
# conftest's fake-env-var one) has run, and CI's "Run tests" step doesn't
# set OPENROUTER_API_KEY at all — so any module that imports this one at
# collection time took the whole suite down before main.py ever ran.
# config.validate() is the actual gate for "is a real key configured";
# this fallback just keeps import-time inert.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY or "unset",
)

# Route to currently available free models instead of retired fixed model IDs.
# https://openrouter.ai/docs/guides/routing/routers/free-router
MODELS = ["openrouter/free"]

BASE_MAX_TOKENS = 400
PER_SIGNAL_TOKENS = 300
MAX_TOKENS_CAP = 2000

SYSTEM_PROMPT = """당신은 중장기 보유 투자자를 위한 애널리스트입니다.
아래로 전달되는 "신호" 목록은 규칙 엔진이 이미 계산과 판정을 끝낸 결과입니다.
당신의 역할은 서식을 채우는 것이 아니라, 각 신호가 왜 중요하고 무엇을 확인해야 하는지 해석하는 것입니다.

규칙:
- 숫자(%, 배수, 가격 등)는 반드시 전달된 신호 데이터에 있는 것만 인용한다. 새로운 숫자를 계산하거나 지어내지 않는다.
- 진입가·손절가 등 단기 매매 신호는 제시하지 않는다. 이 서비스는 중장기 보유자를 대상으로 하며, 그런 데이터 자체가 주어지지 않는다.
- related_news가 있으면 맥락으로 참고하되, 기사에 없는 사실을 지어내지 않는다.
- 신호가 있는 종목만, 종목별로 2~3문장씩 작성한다. "종목명 — 해설" 형식.
- 신호가 여러 개인 종목은 함께 묶어서 설명해도 된다."""


def interpret_signals(signals: list) -> str:
    """Interpret already-detected signals. Numbers can't be invented here —
    they're not computed in this call, only explained.
    """
    if not signals:
        return ""

    max_tokens = min(MAX_TOKENS_CAP, BASE_MAX_TOKENS + PER_SIGNAL_TOKENS * len(signals))
    user_content = json.dumps(signals, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"다음 신호들을 해설해주세요:\n\n{user_content}"},
    ]
    last_err = None
    for model in MODELS:
        try:
            response = client.chat.completions.create(
                model=model, max_tokens=max_tokens, messages=messages
            )
            return response.choices[0].message.content
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"모든 모델 실패: {last_err}")


# Generous: some of the free models in MODELS are reasoning models that think
# out loud before answering, and that preamble alone can run past 800 tokens
# — with a tight budget the response gets cut off before the JSON ever
# appears. Discovery is a single low-frequency call, so the extra budget is cheap.
DISCOVERY_MAX_TOKENS = 2500


def _parse_json_array(content: str) -> list:
    """Extract the JSON array from a model response, not just parse the whole
    string as JSON — reasoning models routinely prepend chain-of-thought
    text before the actual answer, and some wrap it in a markdown fence.
    """
    text = (content or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("ticker")]


def extract_tickers_from_headlines(headlines: list, excluded_symbols: set) -> list:
    """One batch LLM call to pull {ticker, name, mentions} candidates out of
    today's headlines. This is discovery.py's only source of candidate
    tickers — the LLM's output is never trusted as fact. Every ticker here
    still has to survive a real yfinance lookup (discovery.py's hallucination
    guard) before it's shown to anyone; a made-up or mis-matched ticker gets
    silently dropped downstream, not surfaced.
    """
    if not headlines:
        return []

    excluded_text = ", ".join(sorted(excluded_symbols)) if excluded_symbols else "없음"
    prompt = (
        "다음은 오늘자 금융 뉴스 제목 목록입니다. 이 중 언급된 상장회사와 "
        "정확한 거래소 티커(symbol)를 추출해주세요.\n"
        f"이미 관심종목으로 보유 중이라 제외해야 할 티커: {excluded_text}\n\n"
        + "\n".join(f"- {h}" for h in headlines)
        + "\n\n중요: 단계별 추론이나 설명을 출력하지 마세요. 최종 JSON 배열만 바로 출력하세요. 형식: "
        '[{"ticker": "정확한 거래소 티커", "name": "회사명", "mentions": 언급된 제목 개수}]\n'
        "티커를 확신할 수 없으면 그 항목은 포함하지 마세요."
    )
    messages = [{"role": "user", "content": prompt}]

    for model in MODELS:
        try:
            response = client.chat.completions.create(
                model=model, max_tokens=DISCOVERY_MAX_TOKENS, messages=messages,
                # Some free-tier models default to emitting long chain-of-thought
                # before the answer; on a batch task like this (tallying mentions
                # across ~30 headlines) that preamble alone can exceed the token
                # budget and cut off before any JSON appears. This is OpenRouter's
                # unified switch to turn that off — silently ignored by models
                # that don't support it, so it's safe to always send.
                extra_body={"reasoning": {"enabled": False}},
            )
            return _parse_json_array(response.choices[0].message.content)
        except Exception:
            continue
    return []
