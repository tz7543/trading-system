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
