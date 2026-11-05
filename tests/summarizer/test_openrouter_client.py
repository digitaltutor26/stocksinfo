import pytest
from unittest.mock import patch, MagicMock


def _mock_response(text):
    resp = MagicMock()
    resp.choices[0].message.content = text
    return resp


def _signal(symbol="NVDA", severity="yellow", type_="ma200_cross", message="200일선 상향 돌파"):
    return {"symbol": symbol, "severity": severity, "type": type_, "message": message}


def test_interpret_signals_returns_text(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    with patch.object(oc.client.chat.completions, "create",
                      return_value=_mock_response("해설 내용")):
        result = oc.interpret_signals([_signal()])

    assert result == "해설 내용"


def test_interpret_signals_returns_empty_string_without_llm_call_when_no_signals(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    with patch.object(oc.client.chat.completions, "create") as mock_create:
        result = oc.interpret_signals([])

    assert result == ""
    mock_create.assert_not_called()


def test_interpret_signals_falls_back_on_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    monkeypatch.setattr(oc, "MODELS", ["first:free", "second:free"])
    call_count = 0

    def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < len(oc.MODELS):
            raise Exception("rate limit")
        return _mock_response("폴백 결과")

    with patch.object(oc.client.chat.completions, "create", side_effect=mock_create):
        result = oc.interpret_signals([_signal()])

    assert result == "폴백 결과"
    assert call_count > 1


def test_interpret_signals_raises_when_all_models_fail(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    with patch.object(oc.client.chat.completions, "create",
                      side_effect=Exception("all failed")):
        with pytest.raises(RuntimeError, match="모든 모델 실패"):
            oc.interpret_signals([_signal()])


def test_max_tokens_scales_with_signal_count_and_is_capped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    captured = {}

    def mock_create(**kwargs):
        captured["max_tokens"] = kwargs.get("max_tokens")
        return _mock_response("ok")

    with patch.object(oc.client.chat.completions, "create", side_effect=mock_create):
        oc.interpret_signals([_signal()])
    small = captured["max_tokens"]

    with patch.object(oc.client.chat.completions, "create", side_effect=mock_create):
        oc.interpret_signals([_signal() for _ in range(20)])
    large = captured["max_tokens"]

    assert small < large
    assert large <= oc.MAX_TOKENS_CAP


def test_extract_tickers_returns_empty_without_llm_call_when_no_headlines(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    with patch.object(oc.client.chat.completions, "create") as mock_create:
        result = oc.extract_tickers_from_headlines([], set())

    assert result == []
    mock_create.assert_not_called()


def test_extract_tickers_parses_json_array_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    payload = '[{"ticker": "AMD", "name": "AMD", "mentions": 3}]'
    with patch.object(oc.client.chat.completions, "create", return_value=_mock_response(payload)):
        result = oc.extract_tickers_from_headlines(["AMD launches new chip"], {"NVDA"})

    assert result == [{"ticker": "AMD", "name": "AMD", "mentions": 3}]


def test_extract_tickers_handles_markdown_fenced_json(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    payload = '```json\n[{"ticker": "AMD", "name": "AMD", "mentions": 2}]\n```'
    with patch.object(oc.client.chat.completions, "create", return_value=_mock_response(payload)):
        result = oc.extract_tickers_from_headlines(["headline"], set())

    assert result == [{"ticker": "AMD", "name": "AMD", "mentions": 2}]


def test_extract_tickers_returns_empty_on_unparseable_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    with patch.object(oc.client.chat.completions, "create", return_value=_mock_response("not json at all")):
        result = oc.extract_tickers_from_headlines(["headline"], set())

    assert result == []


def test_extract_tickers_returns_empty_when_all_models_fail_no_raise(monkeypatch):
    # Unlike interpret_signals, discovery is best-effort — a total LLM outage
    # shouldn't break the rest of the run, just skip discovery for the day.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    with patch.object(oc.client.chat.completions, "create", side_effect=Exception("down")):
        result = oc.extract_tickers_from_headlines(["headline"], set())

    assert result == []


def test_extract_tickers_handles_reasoning_model_preamble(monkeypatch):
    # Regression: reasoning models on the free tier think out loud before
    # answering — the JSON array has to be found and extracted, not assumed
    # to be the entire response.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    payload = (
        "We need to scan each headline for company names and map them to "
        "tickers. Let's go through the list one by one...\n\n"
        'Final answer: [{"ticker": "AMD", "name": "AMD", "mentions": 2}]'
    )
    with patch.object(oc.client.chat.completions, "create", return_value=_mock_response(payload)):
        result = oc.extract_tickers_from_headlines(["headline"], set())

    assert result == [{"ticker": "AMD", "name": "AMD", "mentions": 2}]


def test_extract_tickers_ignores_non_dict_or_tickerless_items(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    import importlib
    import summarizer.openrouter_client as oc
    importlib.reload(oc)

    payload = '["not a dict", {"name": "no ticker field"}, {"ticker": "AMD", "mentions": 1}]'
    with patch.object(oc.client.chat.completions, "create", return_value=_mock_response(payload)):
        result = oc.extract_tickers_from_headlines(["headline"], set())

    assert result == [{"ticker": "AMD", "mentions": 1}]
