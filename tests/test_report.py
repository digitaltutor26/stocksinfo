import report


def _sig(symbol, severity, message="테스트 신호"):
    return {"symbol": symbol, "severity": severity, "type": "x", "message": message}


def test_build_no_signal_report_is_short_and_has_no_detail_section():
    text = report.build_no_signal_report(["NVDA", "AAPL"], "2026-08-02", [])
    assert "신호 0건" in text
    assert "상세" not in text
    assert "NVDA" in text and "AAPL" in text


def test_build_header_groups_by_severity():
    signals = [_sig("NVDA", "red", "200일선 하향 이탈"), _sig("AAPL", "yellow", "PER 밴드 상단")]
    header = report.build_header(signals, ["NVDA", "AAPL", "TSLA"], "2026-08-02")
    assert "🔴 확인 필요 (1)" in header
    assert "🟡 관찰 (1)" in header
    assert "⚪ 정상 범위 (1)" in header
    assert "TSLA" in header
    assert "신호 2건" in header


def test_build_header_omits_empty_groups():
    header = report.build_header([], ["NVDA"], "2026-08-02")
    assert "🔴" not in header
    assert "🟡" not in header
    assert "⚪ 정상 범위 (1)" in header


def test_build_report_includes_calendar_and_detail():
    signals = [_sig("NVDA", "yellow")]
    text = report.build_report(signals, ["NVDA"], "2026-08-02", ["NVDA 실적(수)"], detail_text="NVDA — 해설")
    assert "📅 이번 주  NVDA 실적(수)" in text
    assert "상세" in text
    assert "NVDA — 해설" in text
    assert "투자 참고용" in text


def test_build_report_without_detail_has_no_detail_section():
    signals = [_sig("NVDA", "yellow")]
    text = report.build_report(signals, ["NVDA"], "2026-08-02", [])
    assert "상세" not in text


def test_format_position_summary_all_fields():
    assert report.format_position_summary(
        {"week52_pct": 22.5, "pct_vs_ma200": -12.34, "relative_strength_6m_pct": 4.56},
        {"trailing_pe": 19.84},
    ) == "52주 밴드 22.5% · 200일선 -12.3% · 6M 상대강도 +4.6%p · PER 19.8배"


def test_format_position_summary_omits_none_fields():
    assert report.format_position_summary(
        {"week52_pct": 50.0, "pct_vs_ma200": None, "relative_strength_6m_pct": None},
        {"trailing_pe": None},
    ) == "52주 밴드 50.0%"


def test_format_position_summary_returns_empty_on_error_or_empty():
    for pos, fund in [(None, None), ({}, {}),
                      ({"error": "timeout", "week52_pct": 88}, {"error": "404", "trailing_pe": 30})]:
        assert report.format_position_summary(pos, fund) == ""
        header = report.build_header(
            [_sig("NVDA", "yellow")], ["NVDA"], "2026-08-02",
            watchlist={"NVDA": pos}, fundamentals={"NVDA": fund},
        )
        assert "└" not in header


def test_format_position_summary_zero_and_independent_sources():
    assert report.format_position_summary(
        {"week52_pct": 0, "pct_vs_ma200": 0, "relative_strength_6m_pct": 0},
        {"trailing_pe": 0},
    ) == "52주 밴드 0.0% · 200일선 +0.0% · 6M 상대강도 +0.0%p · PER 0.0배"
    assert report.format_position_summary({"error": "timeout"}, {"trailing_pe": 20}) == "PER 20.0배"
    assert report.format_position_summary({"week52_pct": 50}, {"error": "timeout"}) == "52주 밴드 50.0%"


def test_build_report_includes_position_summary_line():
    text = report.build_report(
        [_sig("NVDA", "yellow")], ["NVDA"], "2026-08-02", [], detail_text="해설",
        watchlist={"NVDA": {"week52_pct": 88.0, "pct_vs_ma200": 14.2, "relative_strength_6m_pct": -3.5}},
        fundamentals={"NVDA": {"trailing_pe": 28.5}},
    )
    assert "  NVDA    테스트 신호\n    └ 52주 밴드 88.0% · 200일선 +14.2% · 6M 상대강도 -3.5%p · PER 28.5배" in text


def test_build_header_includes_summary_after_red_and_yellow_signals():
    signals = [_sig("NVDA", "red"), _sig("AAPL", "yellow")]
    text = report.build_header(
        signals, ["NVDA", "AAPL"], "2026-08-02",
        watchlist={"NVDA": {"week52_pct": 20}}, fundamentals={"AAPL": {"trailing_pe": 30}},
    )
    assert "  NVDA    테스트 신호\n    └ 52주 밴드 20.0%" in text
    assert "  AAPL    테스트 신호\n    └ PER 30.0배" in text


def test_report_calls_without_context_preserve_output():
    signals = [_sig("NVDA", "yellow")]
    header = report.build_header(signals, ["NVDA"], "2026-08-02")
    assert header == "\n".join([
        report.RULE, "📊 2026-08-02   신호 1건", report.RULE, "",
        "🟡 관찰 (1)", "  NVDA    테스트 신호",
    ])
    for context in [None, {}, {"NVDA": {"last_close": 100}}]:
        assert report.build_header(signals, ["NVDA"], "2026-08-02", context, {}) == header
        assert report.build_report(signals, ["NVDA"], "2026-08-02", [], "해설", context, {}) == (
            header + "\n\n─── 상세 " + "─" * 20 + "\n해설\n\n" + report.DISCLAIMER
        )
