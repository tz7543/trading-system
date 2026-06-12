# apps/trader/tests/test_scan.py
import pytest
from pydantic import ValidationError

from trading_app.config import ScannerConfig, TraderConfig


def test_scanner_config_defaults():
    cfg = ScannerConfig(symbols=["AAPL"], equity=50_000)
    assert cfg.risk_pct == 0.015
    assert cfg.vix is None


def test_scanner_config_rejects_bad_values():
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=[], equity=50_000)
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=["AAPL"], equity=0)
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=["AAPL"], equity=1, risk_pct=0.06)
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=["AAPL"], equity=1, vix=-1)
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=["AAPL"], equity=1, extra_field=1)


def test_trader_config_scanner_section_optional():
    assert TraderConfig().scanner is None
    cfg = TraderConfig.model_validate(
        {"scanner": {"symbols": ["AAPL", "MSFT"], "equity": 100000}}
    )
    assert cfg.scanner.symbols == ["AAPL", "MSFT"]


from strategy.swing.scanner import ScanResult  # noqa: E402
from trading_app.scan_report import json_payload, render_report  # noqa: E402


def _results():
    return [
        ScanResult(symbol="SKP", verdict="SKIP", reasons=["fetch failed: x"]),
        ScanResult(
            symbol="CND",
            verdict="CANDIDATE",
            reasons=[],
            entry=101.23456,
            stop=98.7,
            stop_basis="ma",
            t1=110.0,
            t1_fallback=False,
            rr=3.27654,
            confirmations={
                "squeeze": True,
                "trigger": True,
                "volume": True,
                "momentum": True,
            },
            shares=59,
            multipliers={"atr": 1.0, "vix": None},
            exit_plan={"ma5": 100.9, "ma10": 100.5, "ma20": 99.8, "time_stop": "t"},
            manual_checklist=["check1"],
            indicator_snapshot={
                "adx": 31.2,
                "atr14": 1.9,
                "atr_ratio": 1.1,
                "bb_width": 0.04,
                "bb_width_p20": 0.03,
                "macd_dif": 0.5,
                "macd_dea": 0.4,
                "macd_hist": 0.1,
            },
        ),
    ]


def test_render_report_sorts_candidates_first():
    text = render_report(_results())
    assert text.index("CND") < text.index("SKP")
    assert "check1" in text  # manual checklist appears in detail block
    assert "confirmations:" in text  # four-confirmation status line
    assert "gates:" in text  # gate values from the snapshot


def test_json_payload_schema_and_rounding():
    payload = json_payload(_results(), generated_at="2026-06-12T22:00:00+00:00")
    assert payload["generated_at"] == "2026-06-12T22:00:00+00:00"
    by_symbol = {r["symbol"]: r for r in payload["results"]}
    assert by_symbol["CND"]["entry"] == 101.2346  # 4-dp rounding
    assert by_symbol["CND"]["rr"] == 3.2765
    assert by_symbol["CND"]["stop_basis"] == "ma"
    assert by_symbol["CND"]["confirmations"]["trigger"] is True
    assert by_symbol["SKP"]["indicator_snapshot"] is None
    assert by_symbol["SKP"]["confirmations"] is None
    assert by_symbol["SKP"]["entry"] is None
