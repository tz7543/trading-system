from core.models import Greeks


def test_greeks_add():
    a = Greeks(delta=10.0, gamma=2.0, vega=5.0, theta=-3.0)
    b = Greeks(delta=-5.0, gamma=1.0, vega=3.0, theta=-1.0)
    result = a + b
    assert result.delta == 5.0
    assert result.gamma == 3.0
    assert result.vega == 8.0
    assert result.theta == -4.0


def test_greeks_mul():
    g = Greeks(delta=0.50, gamma=0.03, vega=0.18, theta=-0.05)
    result = g * 100
    assert result.delta == 50.0
    assert result.gamma == 3.0
    assert abs(result.vega - 18.0) < 1e-10
    assert result.theta == -5.0


def test_greeks_rmul():
    g = Greeks(delta=0.50, gamma=0.03, vega=0.18, theta=-0.05)
    result = 100 * g
    assert result.delta == 50.0
    assert result.gamma == 3.0


def test_greeks_add_preserves_zero_implied_vol():
    a = Greeks(delta=1.0, implied_vol=0.25)
    b = Greeks(delta=2.0, implied_vol=0.30)
    result = a + b
    assert result.implied_vol == 0.0
    assert result.underlying_price == 0.0


def test_greeks_chain():
    g1 = Greeks(delta=0.50, gamma=0.03)
    g2 = Greeks(delta=-0.30, gamma=0.04)
    result = g1 * 100 + g2 * -100
    assert result.delta == 80.0
    assert result.gamma == -1.0
