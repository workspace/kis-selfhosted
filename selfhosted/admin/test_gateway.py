"""Unit tests for gateway routing and rewrite functions."""

import pytest
from gateway import passthrough, strip_prefix, match_route, Route


# ─── passthrough ─────────────────────────────────────────────────────────────

class TestPassthrough:
    def test_preserves_path(self):
        rewrite = passthrough()
        assert rewrite("/strategy/foo/bar") == "/strategy/foo/bar"

    def test_preserves_root(self):
        rewrite = passthrough()
        assert rewrite("/") == "/"


# ─── strip_prefix ────────────────────────────────────────────────────────────

class TestStripPrefix:
    def test_strips_prefix(self):
        rewrite = strip_prefix("/strategy")
        assert rewrite("/strategy/api/orders") == "/api/orders"

    def test_strips_to_default_when_empty(self):
        rewrite = strip_prefix("/strategy")
        assert rewrite("/strategy") == "/"

    def test_custom_default(self):
        rewrite = strip_prefix("/mcp/trading", "/mcp")
        assert rewrite("/mcp/trading") == "/mcp"

    def test_mcp_subpath(self):
        rewrite = strip_prefix("/mcp/trading", "/mcp")
        assert rewrite("/mcp/trading/mcp") == "/mcp"

    def test_mcp_deep_path(self):
        rewrite = strip_prefix("/mcp/trading", "/mcp")
        assert rewrite("/mcp/trading/mcp/list/tools") == "/mcp/list/tools"

    def test_mcp_backtest(self):
        rewrite = strip_prefix("/mcp/backtest", "/mcp")
        assert rewrite("/mcp/backtest/mcp") == "/mcp"

    def test_no_double_mcp_prefix(self):
        """Regression: /mcp/trading/mcp must NOT become /mcp/mcp."""
        rewrite = strip_prefix("/mcp/trading", "/mcp")
        result = rewrite("/mcp/trading/mcp")
        assert result == "/mcp"
        assert "/mcp/mcp" not in result

    def test_passthrough_when_no_match(self):
        rewrite = strip_prefix("/strategy")
        assert rewrite("/other/path") == "/other/path"


# ─── match_route ─────────────────────────────────────────────────────────────

class TestMatchRoute:
    def test_strategy_api(self):
        route = match_route("/strategy/api/orders")
        assert route is not None
        assert route.upstream == "http://strategy-backend:8000"

    def test_strategy_frontend(self):
        route = match_route("/strategy/page")
        assert route is not None
        assert route.upstream == "http://strategy-frontend:3000"

    def test_mcp_trading(self):
        route = match_route("/mcp/trading/mcp")
        assert route is not None
        assert route.upstream == "http://trading-mcp:3100"
        assert route.auth_mode == "bearer"

    def test_mcp_backtest(self):
        route = match_route("/mcp/backtest/mcp")
        assert route is not None
        assert route.upstream == "http://backtest-mcp:3846"
        assert route.auth_mode == "bearer"

    def test_no_match(self):
        assert match_route("/unknown/path") is None

    def test_exact_prefix_no_trailing_slash(self):
        route = match_route("/strategy")
        assert route is not None
        assert route.upstream == "http://strategy-frontend:3000"

    def test_api_before_frontend(self):
        """Ensure /strategy/api/ matches backend, not frontend."""
        route = match_route("/strategy/api/health")
        assert route.upstream == "http://strategy-backend:8000"


# ─── End-to-end rewrite via route ────────────────────────────────────────────

class TestRouteRewrite:
    def test_strategy_api_rewrite(self):
        route = match_route("/strategy/api/orders")
        assert route.rewrite("/strategy/api/orders") == "/api/orders"

    def test_strategy_frontend_passthrough(self):
        route = match_route("/strategy/page")
        assert route.rewrite("/strategy/page") == "/strategy/page"

    def test_mcp_trading_rewrite(self):
        route = match_route("/mcp/trading/mcp")
        assert route.rewrite("/mcp/trading/mcp") == "/mcp"

    def test_mcp_trading_exact(self):
        route = match_route("/mcp/trading")
        assert route.rewrite("/mcp/trading") == "/mcp"

    def test_backtest_api_rewrite(self):
        route = match_route("/backtest/api/run")
        assert route.rewrite("/backtest/api/run") == "/api/run"
