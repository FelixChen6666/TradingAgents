"""Tests for symbol normalization and the no-data routing sentinel."""

import unittest

import pytest

from tradingagents.dataflows.symbol_utils import (
    NoMarketDataError,
    SymbolFormatError,
    get_akshare_market,
    get_eastmoney_secid,
    get_pure_code,
    get_sina_prefix,
    is_a_share,
    is_shanghai_a_share,
    is_shenzhen_a_share,
    normalize_symbol,
    is_yahoo_safe,
    strip_prefix_market,
    to_a_share_code,
)


@pytest.mark.unit
class TestNormalizeSymbol(unittest.TestCase):
    def test_plain_equities_unchanged(self):
        for sym in ("AAPL", "MSFT", "TSM", "BRK.B", "0700.HK", "^GSPC", "GC=F"):
            self.assertEqual(normalize_symbol(sym), sym)

    def test_lowercases_are_upper(self):
        self.assertEqual(normalize_symbol("aapl"), "AAPL")
        self.assertEqual(normalize_symbol("  msft  "), "MSFT")

    def test_metal_aliases_map_to_futures(self):
        self.assertEqual(normalize_symbol("XAUUSD"), "GC=F")
        self.assertEqual(normalize_symbol("XAUUSD+"), "GC=F")   # broker CFD suffix
        self.assertEqual(normalize_symbol("xauusd+"), "GC=F")
        self.assertEqual(normalize_symbol("GOLD"), "GC=F")
        self.assertEqual(normalize_symbol("XAGUSD"), "SI=F")

    def test_energy_and_index_aliases(self):
        self.assertEqual(normalize_symbol("USOIL"), "CL=F")
        self.assertEqual(normalize_symbol("SPX500"), "^GSPC")
        self.assertEqual(normalize_symbol("NAS100"), "^NDX")
        self.assertEqual(normalize_symbol("US30"), "^DJI")

    def test_forex_pairs_get_x_suffix(self):
        self.assertEqual(normalize_symbol("EURUSD"), "EURUSD=X")
        self.assertEqual(normalize_symbol("GBPJPY"), "GBPJPY=X")
        self.assertEqual(normalize_symbol("eurusd"), "EURUSD=X")

    def test_crypto_pairs_get_dash_usd(self):
        self.assertEqual(normalize_symbol("BTCUSD"), "BTC-USD")
        self.assertEqual(normalize_symbol("ETHUSD"), "ETH-USD")

    def test_six_letter_non_currency_left_alone(self):
        # GOOGLE-style 6-letter tickers that aren't two currency codes
        # must not be mangled into a fake forex pair.
        self.assertEqual(normalize_symbol("ABCDEF"), "ABCDEF")

    def test_empty_input_passthrough(self):
        self.assertEqual(normalize_symbol(""), "")


@pytest.mark.unit
class TestNoMarketDataError(unittest.TestCase):
    def test_message_includes_resolution(self):
        err = NoMarketDataError("XAUUSD+", "GC=F", "no rows")
        self.assertIn("XAUUSD+", str(err))
        self.assertIn("GC=F", str(err))
        self.assertEqual(err.symbol, "XAUUSD+")
        self.assertEqual(err.canonical, "GC=F")

    def test_canonical_defaults_to_symbol(self):
        err = NoMarketDataError("FOOBAR")
        self.assertEqual(err.canonical, "FOOBAR")


@pytest.mark.unit
class TestIsYahooSafe(unittest.TestCase):
    def test_accepts_structural_chars(self):
        for sym in ("AAPL", "GC=F", "^GSPC", "BRK.B", "BTC-USD"):
            self.assertTrue(is_yahoo_safe(sym))

    def test_rejects_slash_and_space(self):
        for sym in ("a/b", "AA PL", ""):
            self.assertFalse(is_yahoo_safe(sym))


@pytest.mark.unit
class TestGetPureCode(unittest.TestCase):
    def test_strips_suffix(self):
        self.assertEqual(get_pure_code("600519"), "600519")
        self.assertEqual(get_pure_code("600519.SH"), "600519")
        self.assertEqual(get_pure_code("600519.SZ"), "600519")
        self.assertEqual(get_pure_code("600519.SS"), "600519")

    def test_uppercases(self):
        self.assertEqual(get_pure_code("aapl"), "AAPL")
        self.assertEqual(get_pure_code("  msft  "), "MSFT")

    def test_preserves_unrecognised_chars(self):
        # No suffix to strip; pass through (still uppercased).
        self.assertEqual(get_pure_code("BRK.B"), "BRK.B")

    def test_hk_suffix(self):
        self.assertEqual(get_pure_code("00700.HK"), "00700")


@pytest.mark.unit
class TestIsShanghaiShenzhenA(unittest.TestCase):
    def test_shanghai_codes(self):
        for sym in ("600519", "600519.SH", "688001.SH", "900901"):
            self.assertTrue(is_shanghai_a_share(sym), sym)
        self.assertTrue(is_shanghai_a_share("688001"))  # 科创板
        self.assertTrue(is_shanghai_a_share("601318"))  # 601xxx
        self.assertTrue(is_shanghai_a_share("603259"))  # 603xxx
        self.assertTrue(is_shanghai_a_share("605499"))  # 605xxx
        self.assertTrue(is_shanghai_a_share("689009"))  # 689xxx 科创板扩展

    def test_shenzhen_codes(self):
        for sym in ("000001", "000001.SZ", "300001", "002001"):
            self.assertTrue(is_shenzhen_a_share(sym), sym)
        self.assertTrue(is_shenzhen_a_share("001979"))  # 001xxx 中小板
        self.assertTrue(is_shenzhen_a_share("003816"))  # 003xxx
        self.assertTrue(is_shenzhen_a_share("301236"))  # 301xxx 创业板
        self.assertTrue(is_shenzhen_a_share("200002"))  # 200xxx B股

    def test_not_a_share(self):
        self.assertFalse(is_shanghai_a_share("AAPL"))
        self.assertFalse(is_shenzhen_a_share("AAPL"))
        self.assertFalse(is_shanghai_a_share("12345"))  # 5-digit (HK)
        self.assertFalse(is_shenzhen_a_share("12345"))

    def test_bj_exchange_rejected(self):
        # 北交所 8/4 开头不应被识别为 A 股
        # (830001, 430047 等)
        for sym in ("830001", "430047", "830001.BJ"):
            self.assertFalse(is_a_share(sym), sym)
            self.assertFalse(is_shanghai_a_share(sym), sym)
            self.assertFalse(is_shenzhen_a_share(sym), sym)

    def test_invalid_6digit_rejected(self):
        # 不是真实 A 股段但 6 位数字的代码必须被拒
        # (与原 eastmoney_news.py 用 startswith(("6","9","68")) 相比修复)
        for sym in ("666666", "777777", "123456", "888888"):
            self.assertFalse(is_a_share(sym), sym)
            self.assertFalse(is_shanghai_a_share(sym), sym)
            self.assertFalse(is_shenzhen_a_share(sym), sym)

    def test_shanghai_not_shenzhen(self):
        self.assertFalse(is_shenzhen_a_share("600519"))
        self.assertFalse(is_shanghai_a_share("000001"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol,expected",
    [
        # Shanghai (secid prefix 1)
        pytest.param("600519", "1.600519", id="sh-bare"),
        pytest.param("600519.SH", "1.600519", id="sh-suffix"),
        pytest.param("SH600519", "1.600519", id="sh-prefix-upper"),
        pytest.param("sh600519", "1.600519", id="sh-prefix-lower"),
        pytest.param("688001", "1.688001", id="sh-科创板"),
        pytest.param("900901", "1.900901", id="sh-B股"),
        # Shenzhen (secid prefix 0)
        pytest.param("000001", "0.000001", id="sz-bare"),
        pytest.param("000001.SZ", "0.000001", id="sz-suffix"),
        pytest.param("SZ000001", "0.000001", id="sz-prefix"),
        pytest.param("300001", "0.300001", id="sz-创业板"),
        pytest.param("002001", "0.002001", id="sz-中小板"),
    ],
)
def test_get_eastmoney_secid_valid(symbol, expected):
    assert get_eastmoney_secid(symbol) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol",
    [
        pytest.param("AAPL", id="us-equity"),
        pytest.param("12345", id="hk-5digit"),
        pytest.param("", id="empty"),
        # 北交所必须被拒 (bug fix 回归)
        pytest.param("830001", id="bj-8xx"),
        pytest.param("430047", id="bj-4xx"),
        pytest.param("830001.BJ", id="bj-suffix"),
        pytest.param("BJ830001", id="bj-prefix"),
        # 无效 6 位数字必须被拒 (bug fix 回归)
        pytest.param("666666", id="invalid-666666"),
        pytest.param("777777", id="invalid-777777"),
        pytest.param("888888", id="invalid-888888"),
        pytest.param("123456", id="invalid-123456"),
    ],
)
def test_get_eastmoney_secid_rejects(symbol):
    with pytest.raises(SymbolFormatError) as exc:
        get_eastmoney_secid(symbol)
    assert exc.value.vendor == "eastmoney"
    assert exc.value.symbol == symbol


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol,expected",
    [
        pytest.param("600519", "sh", id="sh-bare"),
        pytest.param("600519.SH", "sh", id="sh-suffix"),
        pytest.param("SH600519", "sh", id="sh-prefix"),
        pytest.param("688001", "sh", id="sh-科创板"),
        pytest.param("000001", "sz", id="sz-bare"),
        pytest.param("000001.SZ", "sz", id="sz-suffix"),
        pytest.param("SZ000001", "sz", id="sz-prefix"),
        pytest.param("300001", "sz", id="sz-创业板"),
    ],
)
def test_get_sina_prefix_valid(symbol, expected):
    assert get_sina_prefix(symbol) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol",
    [
        pytest.param("AAPL", id="us-equity"),
        pytest.param("12345", id="hk-5digit"),
        pytest.param("", id="empty"),
        pytest.param("830001", id="bj-8xx"),
        pytest.param("666666", id="invalid-6digit"),
    ],
)
def test_get_sina_prefix_rejects(symbol):
    with pytest.raises(SymbolFormatError) as exc:
        get_sina_prefix(symbol)
    assert exc.value.vendor == "sina"
    assert exc.value.symbol == symbol


@pytest.mark.unit
class TestGetAkshareMarket(unittest.TestCase):
    def test_a_share(self):
        self.assertEqual(get_akshare_market("600519"), "a_share")
        self.assertEqual(get_akshare_market("000001.SZ"), "a_share")
        self.assertEqual(get_akshare_market("300001"), "a_share")

    def test_hk(self):
        self.assertEqual(get_akshare_market("00700"), "hk")
        self.assertEqual(get_akshare_market("00700.HK"), "hk")
        self.assertEqual(get_akshare_market("09988.HK"), "hk")

    def test_unsupported(self):
        self.assertEqual(get_akshare_market("AAPL"), "unsupported")
        self.assertEqual(get_akshare_market("EURUSD"), "unsupported")
        self.assertEqual(get_akshare_market(""), "unsupported")
        self.assertEqual(get_akshare_market(None), "unsupported")


@pytest.mark.unit
class TestStripPrefixMarket(unittest.TestCase):
    def test_strips_prefix(self):
        self.assertEqual(strip_prefix_market("SH600519"), "600519")
        self.assertEqual(strip_prefix_market("SZ000001"), "000001")
        self.assertEqual(strip_prefix_market("BJ830001"), "830001")
        self.assertEqual(strip_prefix_market("SS600519"), "600519")

    def test_passthrough(self):
        self.assertEqual(strip_prefix_market("600519"), "600519")
        self.assertEqual(strip_prefix_market("AAPL"), "AAPL")

    def test_guards_against_false_match(self):
        # "SH" must be followed by a digit, not another letter.
        self.assertEqual(strip_prefix_market("SHOP"), "SHOP")
        self.assertEqual(strip_prefix_market("SH"), "SH")


@pytest.mark.unit
class TestToAShareCode(unittest.TestCase):
    def test_bare_code(self):
        self.assertEqual(to_a_share_code("600519"), "600519")

    def test_suffix_form(self):
        self.assertEqual(to_a_share_code("600519.SH"), "600519")
        self.assertEqual(to_a_share_code("000001.SZ"), "000001")
        self.assertEqual(to_a_share_code("000001.SS"), "000001")

    def test_prefix_form(self):
        self.assertEqual(to_a_share_code("SH600519"), "600519")
        self.assertEqual(to_a_share_code("SZ000001"), "000001")
        self.assertEqual(to_a_share_code("BJ830001"), "830001")

    def test_combined_form(self):
        # Defensive: even if user types both prefix and suffix.
        self.assertEqual(to_a_share_code("SH600519.SH"), "600519")

    def test_uppercases(self):
        self.assertEqual(to_a_share_code("sh600519"), "600519")

    def test_whitespace(self):
        self.assertEqual(to_a_share_code("  600519  "), "600519")


@pytest.mark.unit
class TestIsAShareBehaviour(unittest.TestCase):
    """Sanity checks for the existing is_a_share() helper that all
    vendor modules now use as a single source of truth."""

    def test_true_for_a_share(self):
        self.assertTrue(is_a_share("600519"))
        self.assertTrue(is_a_share("000001"))
        self.assertTrue(is_a_share("300001"))

    def test_false_for_non_a_share(self):
        self.assertFalse(is_a_share("AAPL"))
        self.assertFalse(is_a_share("00700.HK"))
        self.assertFalse(is_a_share("EURUSD"))


if __name__ == "__main__":
    unittest.main()
