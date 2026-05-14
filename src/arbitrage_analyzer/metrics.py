import os
from decimal import Decimal

from prometheus_client import Counter, Gauge, Histogram, start_http_server


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


METRICS_ADDR = _env_str("METRICS_ADDR", "127.0.0.1")
METRICS_PORT = _env_int("METRICS_PORT", 9100)

BLOCKS_SCANNED = Counter(
    "blocks_scanned",
    "Total number of historical Ethereum blocks scanned by the backtest.",
)

ANVIL_RESET_LATENCY_MS = Histogram(
    "anvil_reset_latency_ms",
    "Latency of anvil_reset per historical block in milliseconds.",
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
)

ETH_CALL_TOTAL = Counter(
    "eth_call_total",
    "Total number of eth_call executions against historical Ethereum state.",
)

ETH_CALL_ERRORS_TOTAL = Counter(
    "eth_call_errors_total",
    "Total number of failed eth_call executions against historical Ethereum state.",
)

POOLS_DISCOVERED_TOTAL = Counter(
    "pools_discovered_total",
    "Total number of discovered pools by DEX and pool type.",
    ["dex", "type"],
)

ROUTES_EVALUATED_TOTAL = Counter(
    "routes_evaluated_total",
    "Total number of evaluated arbitrage routes by route type.",
    ["route_type"],
)

# 7) Computational cost for V3 routes
OPTIMIZER_ITERATIONS_TOTAL = Counter(
    "optimizer_iterations_total",
    "Total number of numerical optimizer iterations.",
)

GROSS_OPPORTUNITIES_TOTAL = Counter(
    "gross_opportunities_total",
    "Total number of positive gross arbitrage opportunities found.",
)

GROSS_PROFIT_USD_APPROX_TOTAL = Counter(
    "gross_profit_usd_approx_total",
    "Cumulative approximate USD gross profit across detected opportunities.",
)

GROSS_PROFIT_USD_APPROX_MAX = Gauge(
    "gross_profit_usd_approx_max",
    "Maximum approximate USD gross profit observed for a single opportunity.",
)

_gross_profit_usd_approx_max_seen = 0.0


def start_metrics_server() -> None:
    start_http_server(METRICS_PORT)
    print(f"[metrics] Prometheus endpoint started: http://{METRICS_ADDR}:{METRICS_PORT}/metrics")


def observe_gross_profit_usd_approx(value) -> None:
    global _gross_profit_usd_approx_max_seen

    value_float = float(Decimal(str(value)))

    if value_float <= 0:
        return

    GROSS_PROFIT_USD_APPROX_TOTAL.inc(value_float)

    if value_float > _gross_profit_usd_approx_max_seen:
        _gross_profit_usd_approx_max_seen = value_float
        GROSS_PROFIT_USD_APPROX_MAX.set(value_float)