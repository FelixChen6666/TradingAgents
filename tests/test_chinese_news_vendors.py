"""Tests for the A-share sentiment news vendors (Guba + Xueqiu).

Covers:
  - non-A-share ticker is rejected with a placeholder (no exception)
  - network failure / non-200 / unparseable HTML returns a placeholder
  - happy path: well-formed HTML is parsed into a markdown block
  - happy path: well-formed JSON is parsed into a markdown block
  - rate limiter is invoked at least once per page
  - extraction helpers are robust to malformed input
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from tradingagents.dataflows import chinese_news_guba, chinese_news_xueqiu


# ---------------------------------------------------------------------------
# Guba
# ---------------------------------------------------------------------------

_SAMPLE_GUBA_HTML = """
<html><body>
<table>
  <tr class="listitem">
    <td class="title">
      <a href="/news,600519,123456789.html">今天大涨！主力资金流入</a>
    </td>
    <td class="author"><a>散户甲</a></td>
    <td class="update">06-08 11:35</td>
    <td class="read">1234</td>
    <td class="reply">56</td>
  </tr>
  <tr class="listitem">
    <td class="title">
      <a href="/news,600519,987654321.html">业绩超预期，下周继续看多</a>
    </td>
    <td class="author"><a>价投乙</a></td>
    <td class="update">06-08 10:21</td>
    <td class="read">2345</td>
    <td class="reply">78</td>
  </tr>
</table>
</body></html>
"""

_EMPTY_GUBA_HTML = "<html><body><table></table></body></html>"


@pytest.mark.unit
class TestGubaHelpers:
    def test_extract_post_id(self):
        assert chinese_news_guba._extract_post_id(
            "/news,600519,123456789.html"
        ) == "123456789"

    def test_extract_post_id_empty(self):
        assert chinese_news_guba._extract_post_id("") == ""
        assert chinese_news_guba._extract_post_id("/news.html") == ""

    def test_parse_post_list_extracts_two_rows(self):
        posts = chinese_news_guba._parse_post_list(_SAMPLE_GUBA_HTML, "600519")
        assert len(posts) == 2
        assert posts[0]["title"] == "今天大涨！主力资金流入"
        assert posts[0]["post_id"] == "123456789"
        assert posts[0]["author"] == "散户甲"
        assert posts[0]["read_count"] == "1234"
        assert posts[0]["reply_count"] == "56"

    def test_parse_post_list_handles_empty(self):
        assert chinese_news_guba._parse_post_list(_EMPTY_GUBA_HTML, "600519") == []

    def test_to_code_strips_suffix(self):
        assert chinese_news_guba._to_code("600519.SH") == "600519"
        assert chinese_news_guba._to_code("SH600519") == "600519"
        assert chinese_news_guba._to_code("000001.SZ") == "000001"

    def test_is_a_share_accepts_valid_codes(self):
        assert chinese_news_guba._is_a_share("600519")
        assert chinese_news_guba._is_a_share("000001")
        assert chinese_news_guba._is_a_share("300750")

    def test_is_a_share_rejects_invalid(self):
        assert not chinese_news_guba._is_a_share("AAPL")
        assert not chinese_news_guba._is_a_share("123")  # too short


@pytest.mark.unit
class TestGubaFetch:
    def _resp(self, status_code: int, text: str = ""):
        r = requests.Response()
        r.status_code = status_code
        r._content = text.encode("utf-8")
        r.encoding = "utf-8"
        return r

    def test_happy_path(self):
        with patch.object(
            chinese_news_guba.requests, "get",
            return_value=self._resp(200, _SAMPLE_GUBA_HTML),
        ) as get_mock:
            out = chinese_news_guba.get_guba_posts("600519", pages=1, limit=5)

        assert "East Money Guba Posts — 600519" in out
        assert "今天大涨！主力资金流入" in out
        assert "业绩超预期" in out
        assert "散户甲" in out
        assert "read=1234" in out
        assert "reply=56" in out
        assert get_mock.call_count == 1

    def test_non_a_share_returns_placeholder(self):
        out = chinese_news_guba.get_guba_posts("AAPL")
        assert out.startswith("<guba not applicable")
        assert "AAPL" in out

    def test_http_500_returns_unavailable(self):
        with patch.object(
            chinese_news_guba.requests, "get",
            return_value=self._resp(500),
        ):
            out = chinese_news_guba.get_guba_posts("600519", pages=2, limit=5)
        assert out.startswith("<guba unavailable")

    def test_network_exception_returns_unavailable(self):
        with patch.object(
            chinese_news_guba.requests, "get",
            side_effect=requests.ConnectionError("boom"),
        ):
            out = chinese_news_guba.get_guba_posts("600519", pages=1, limit=5)
        assert out.startswith("<guba unavailable")

    def test_empty_parsed_pages_returns_no_data(self):
        with patch.object(
            chinese_news_guba.requests, "get",
            return_value=self._resp(200, _EMPTY_GUBA_HTML),
        ):
            out = chinese_news_guba.get_guba_posts("600519", pages=1, limit=5)
        # empty HTML = no posts parsed on the first page → "unavailable"
        # (could also be no_data_found depending on heuristic)
        assert "<guba" in out or "<no discussion posts" in out

    def test_rate_limiter_invoked(self):
        with patch.object(
            chinese_news_guba.requests, "get",
            return_value=self._resp(200, _SAMPLE_GUBA_HTML),
        ), patch.object(
            chinese_news_guba._rate_limiter, "wait_if_needed",
        ) as wait:
            chinese_news_guba.get_guba_posts("600519", pages=1, limit=5)
        assert wait.call_args.args == ("chinese_guba",)


# ---------------------------------------------------------------------------
# Xueqiu
# ---------------------------------------------------------------------------

_SAMPLE_XQ_PAYLOAD = {
    "list": [
        {
            "id": 200000001,
            "text": "<em>贵州茅台</em>业绩超预期，机构看多至2500元",
            "user": {"id": 100, "screen_name": "价投大佬"},
            "timeBefore": "5分钟前",
            "created_at": 1717838400000,
            "retweet_count": 5,
            "reply_count": 23,
            "fav_count": 12,
        },
        {
            "id": 200000002,
            "text": "今天大盘走弱，茅台也跟着跌",
            "user": {"id": 200, "screen_name": "trader_x"},
            "timeBefore": "30分钟前",
            "created_at": 1717836000000,
            "retweet_count": 0,
            "reply_count": 4,
            "fav_count": 0,
        },
    ],
}

_EMPTY_XQ_PAYLOAD = {"list": []}


def _make_session_with_cookie(*responses):
    """Return a mock session that yields the given response objects in order."""
    session = chinese_news_xueqiu.requests.Session()

    def fake_get(url, **kwargs):
        if not responses:
            raise AssertionError("unexpected extra request")
        return responses.pop(0)

    return session, fake_get


@pytest.mark.unit
class TestXueqiuHelpers:
    def test_to_xueqiu_symbol_sh(self):
        assert chinese_news_xueqiu._to_xueqiu_symbol("600519") == "SH600519"
        assert chinese_news_xueqiu._to_xueqiu_symbol("600519.SH") == "SH600519"
        assert chinese_news_xueqiu._to_xueqiu_symbol("SH600519") == "SH600519"

    def test_to_xueqiu_symbol_sz(self):
        assert chinese_news_xueqiu._to_xueqiu_symbol("000001") == "SZ000001"
        assert chinese_news_xueqiu._to_xueqiu_symbol("300750") == "SZ300750"

    def test_to_xueqiu_symbol_invalid(self):
        assert chinese_news_xueqiu._to_xueqiu_symbol("AAPL") == ""

    def test_strip_html(self):
        assert chinese_news_xueqiu._strip_html(
            "<em>foo</em> bar  baz"
        ) == "foo bar baz"
        assert chinese_news_xueqiu._strip_html("") == ""

    def test_parse_statuses_extracts_two_rows(self):
        rows = chinese_news_xueqiu._parse_statuses(_SAMPLE_XQ_PAYLOAD)
        assert len(rows) == 2
        assert rows[0]["user_name"] == "价投大佬"
        assert "贵州茅台" in rows[0]["text"]  # HTML stripped
        assert "<em>" not in rows[0]["text"]
        assert rows[0]["reply_count"] == 23

    def test_parse_statuses_handles_empty(self):
        assert chinese_news_xueqiu._parse_statuses(_EMPTY_XQ_PAYLOAD) == []
        assert chinese_news_xueqiu._parse_statuses({}) == []
        assert chinese_news_xueqiu._parse_statuses("not a dict") == []


@pytest.mark.unit
class TestXueqiuFetch:
    def _resp(self, status_code: int, json_payload=None, cookies=None):
        """Build a ``requests.Response`` with cookies set if provided."""
        r = requests.Response()
        r.status_code = status_code
        r.encoding = "utf-8"
        if json_payload is not None:
            import json as _json
            r._content = _json.dumps(json_payload).encode("utf-8")
        else:
            r._content = b""
        if cookies:
            for k, v in cookies.items():
                r.cookies.set(k, v)
        return r

    def _make_session(self, *responses):
        """Return a Session whose ``.get`` pops responses in order."""
        session = chinese_news_xueqiu.requests.Session()
        queue = list(responses)

        def fake_get(url, **kwargs):
            if not queue:
                raise AssertionError(f"unexpected extra GET to {url}")
            return queue.pop(0)

        session.get = fake_get
        return session

    def test_non_a_share_returns_placeholder(self):
        out = chinese_news_xueqiu.get_xueqiu_posts("AAPL")
        assert out.startswith("<xueqiu not applicable")
        assert "AAPL" in out

    def test_happy_path(self):
        api_resp = self._resp(200, json_payload=_SAMPLE_XQ_PAYLOAD)
        session = self._make_session(api_resp)

        with patch.object(
            chinese_news_xueqiu.requests, "Session", return_value=session,
        ), patch.object(
            chinese_news_xueqiu, "_bootstrap_cookie", return_value=True,
        ), patch.object(
            chinese_news_xueqiu._rate_limiter, "wait_if_needed",
        ):
            out = chinese_news_xueqiu.get_xueqiu_posts("600519", limit=5)

        assert "Xueqiu (雪球) Posts — 600519" in out
        assert "贵州茅台" in out
        assert "<em>" not in out  # HTML stripped
        assert "价投大佬" in out
        assert "reply=23" in out
        assert "fav=12" in out

    def test_bootstrap_fails_returns_unavailable(self):
        # When the cookie bootstrap returns False, the function bails
        # out before touching the API.
        with patch.object(
            chinese_news_xueqiu, "_bootstrap_cookie", return_value=False,
        ):
            out = chinese_news_xueqiu.get_xueqiu_posts("600519", limit=5)

        assert out.startswith("<xueqiu unavailable")

    def test_api_500_returns_unavailable(self):
        cookie_resp = self._resp(200, cookies={"xq_a_token": "abc"})
        api_500 = self._resp(500)
        session = self._make_session(cookie_resp, api_500)

        with patch.object(
            chinese_news_xueqiu.requests, "Session", return_value=session,
        ), patch.object(
            chinese_news_xueqiu, "_bootstrap_cookie", return_value=True,
        ), patch.object(
            chinese_news_xueqiu._rate_limiter, "wait_if_needed",
        ):
            out = chinese_news_xueqiu.get_xueqiu_posts("600519", limit=5)

        assert out.startswith("<xueqiu unavailable")

    def test_api_returns_empty_list(self):
        cookie_resp = self._resp(200, cookies={"xq_a_token": "abc"})
        empty_resp = self._resp(200, json_payload=_EMPTY_XQ_PAYLOAD)
        session = self._make_session(cookie_resp, empty_resp)

        with patch.object(
            chinese_news_xueqiu.requests, "Session", return_value=session,
        ), patch.object(
            chinese_news_xueqiu, "_bootstrap_cookie", return_value=True,
        ), patch.object(
            chinese_news_xueqiu._rate_limiter, "wait_if_needed",
        ):
            out = chinese_news_xueqiu.get_xueqiu_posts("600519", limit=5)

        # Empty list + no parse error → "no data found" or "unavailable"
        assert "<no discussion posts" in out or "<xueqiu unavailable" in out

    def test_rate_limiter_invoked(self):
        cookie_resp = self._resp(200, cookies={"xq_a_token": "abc"})
        api_resp = self._resp(200, json_payload=_SAMPLE_XQ_PAYLOAD)
        session = self._make_session(cookie_resp, api_resp)

        with patch.object(
            chinese_news_xueqiu.requests, "Session", return_value=session,
        ), patch.object(
            chinese_news_xueqiu, "_bootstrap_cookie", return_value=True,
        ), patch.object(
            chinese_news_xueqiu._rate_limiter, "wait_if_needed",
        ) as wait:
            chinese_news_xueqiu.get_xueqiu_posts("600519", limit=5)

        assert wait.call_args_list[0].args == ("chinese_xueqiu",)
