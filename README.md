---

# Ethereum Historical DEX Arbitrage Analyzer

A Python-based historical Ethereum DEX arbitrage analytics tool that scans past mainnet blocks, discovers Uniswap V2-style and Uniswap V3 pools, evaluates two-hop arbitrage routes, and reports gross arbitrage opportunities before gas and execution costs.

---

## Overview

This project implements a historical DeFi analytics pipeline for studying DEX price differences on Ethereum mainnet.

The analyzer connects to a local Anvil RPC, resets the fork to a selected historical block using an archive Erigon RPC endpoint, reads pool state at that block, and calculates whether a two-hop swap cycle could produce more of the starting token than it consumes.

The goal of this project is not to execute trades, send transactions, build bundles, or compete in the mempool.

Instead, it is an analytical case study focused on understanding how historical DEX arbitrage opportunities can be detected from Ethereum state, AMM pricing, pool discovery, and block-by-block backtesting.

---

## What This Project Demonstrates

This project demonstrates practical work with:

* Ethereum historical state analysis
* Archive node usage with Erigon
* Local fork-based analysis through Anvil
* `anvil_reset` for block-by-block historical replay
* `eth_call` against historical block state
* ABI-based smart contract interaction
* Uniswap V2-compatible factory and pair contracts
* Uniswap V3 factory, pool metadata, and Quoter-based routing
* AMM constant-product pricing
* V2/V2 closed-form arbitrage sizing
* Numerical optimization for routes involving V3
* Gross profit calculation before execution costs
* Python-based DeFi research infrastructure

---

## Important Scope Clarification

This is an analytics tool only.

It does not:

* Send transactions
* Execute swaps
* Build MEV bundles
* Simulate Flashbots bundles
* Interact with private relays
* Submit transactions to the public mempool
* Perform frontrunning, backrunning, or sandwich attacks
* Simulate full transaction execution through an arbitrage contract
* Estimate `gasUsed`
* Calculate final net profit after gas
* Attempt to profit from detected opportunities

The project is designed as a research and engineering case study for historical DEX arbitrage analysis.

It finds mathematical gross opportunities in historical pool states. Any real execution candidate would require additional transaction simulation, gas estimation, revert checks, execution-path validation, and net-profit analysis.

---

## Features

* Historical scan over a configurable block range
* Anvil fork reset before each analyzed block
* Support for archive Erigon RPC as the historical state source
* Discovery of V2-compatible pools through factory contracts
* Discovery of Uniswap V3 pools across multiple fee tiers
* Support for WETH/USDC and WETH/USDT pairs
* Support for Uniswap V2, Sushiswap V2, PancakeSwap V2, and Uniswap V3
* V2 reserve loading through `getReserves()`
* V3 pool metadata loading through `slot0()` and `liquidity()`
* V3 swap output quoting through Uniswap V3 Quoter v1
* Two-hop route evaluation across pool combinations
* Support for V2/V2, V2/V3, V3/V2, and V3/V3 routes
* V2/V2 closed-form optimal input calculation
* Numerical optimization for routes involving V3
* Gross profit and profit percentage calculation
* Approximate USD-like sorting for mixed WETH and stablecoin results
* Debug mode for detailed route, pool, and optimizer diagnostics
* Quiet mode for block-level result summaries

---

## Supported Assets

The current configuration analyzes:

```text
WETH/USDC
WETH/USDT
```

Configured token set:

```text
WETH
USDC
USDT
```

The scanner evaluates two-hop cycles in both starting-token directions when two pools are compared. For example:

```text
WETH -> USDC -> WETH
USDC -> WETH -> USDC

WETH -> USDT -> WETH
USDT -> WETH -> USDT
```

---

## Supported DEX Sources

### V2-compatible DEXes

The scanner discovers V2-style pools through factory contracts:

```text
Uniswap V2
Sushiswap V2
PancakeSwap V2
```

For V2 pools, the analyzer reads:

```text
token0
token1
reserve0
reserve1
fee
spot price
```

### Uniswap V3

The scanner checks Uniswap V3 pools across the standard fee tiers:

```text
0.01%   fee = 100
0.05%   fee = 500
0.30%   fee = 3000
1.00%   fee = 10000
```

For V3 pools, the analyzer reads:

```text
token0
token1
liquidity
sqrtPriceX96
tick
fee
spot price
```

Important: V3 swap output is not calculated by a custom Python implementation of Uniswap V3 tick traversal. The scanner uses historical `eth_call` to the Uniswap V3 Quoter v1. Pool fields such as `sqrtPriceX96`, `tick`, and `liquidity` are used for discovery, validation, and debug output, while quote calculation is delegated to the V3 Quoter.

---

## Architecture

```text
Configured block range
        ↓
For each block
        ↓
Reset local Anvil fork with anvil_reset
        ↓
Use archive Erigon RPC as the fork source
        ↓
Read pool state through historical eth_call
        ↓
Discover V2 and V3 pools for configured pairs
        ↓
Build two-hop pool combinations
        ↓
Evaluate V2/V2, V2/V3, V3/V2, V3/V3 routes
        ↓
Optimize input size for maximum gross profit
        ↓
Sort and print gross arbitrage opportunities
```

---

## Historical Block Backtesting

The user configures a scan range:

```text
START_BLOCK=25000000
FINISH_BLOCK=25000020
```

The analyzer processes blocks sequentially:

```text
25000000
25000001
25000002
...
25000020
```

Before each block is analyzed, the script resets the local Anvil fork:

```text
anvil_reset -> selected historical block
```

The reset uses the archive RPC endpoint as the fork source:

```env
HTTP_ARCHIVE_RPC_URL=
```

This allows the script to analyze Ethereum state as it existed at a specific historical block.

The project was designed for:

```text
Anvil version: 1.5.0-stable
Archive node: Erigon archive node
```

---

## Core Logic

For each selected block, the analyzer follows this pipeline:

1. Reset Anvil to the target block using `anvil_reset`.
2. Set the internal `BLOCK_IDENTIFIER` to the current block number.
3. Discover V2-compatible pools through `getPair(tokenA, tokenB)`.
4. Discover Uniswap V3 pools through `getPool(tokenA, tokenB, fee)`.
5. Load pool reserves and metadata.
6. Build all two-pool combinations for each configured token pair.
7. Evaluate both pool orders and both starting-token directions.
8. Calculate two-hop route output.
9. Compute gross profit as `amount_out - amount_in`.
10. Keep routes where gross profit is positive and above the configured minimum threshold.
11. Sort results by approximate USD-like gross profit.
12. Print the top opportunities for the block.

---

## Arbitrage Definition

The scanner treats a route as a gross arbitrage opportunity when a two-hop swap cycle returns more of the starting asset than it consumes.

General route structure:

```text
token_start -> token_mid -> token_start
```

General formula:

```text
gross_profit = amount_out_final - amount_in
```

If:

```text
gross_profit > 0
```

then the route is reported as a gross opportunity.

Example:

```text
amount_in:    0.307807429245 WETH
amount_mid:   789.255954 USDT
amount_out:   0.307836543956 WETH
gross_profit: 0.000029114711 WETH
profit_pct:   0.00945874%
```

This means that, according to historical pool state and quote calculations, the two-hop route returns slightly more WETH than it starts with.

---

## Route Types

The project supports four route classes:

```text
V2/V2
V2/V3
V3/V2
V3/V3
```

### V2/V2

Both swaps use constant-product AMM math.

For a single V2 swap:

```text
gamma = 1 - fee
amount_in_with_fee = amount_in * gamma
amount_out = amount_in_with_fee * reserve_out / (reserve_in + amount_in_with_fee)
```

For V2/V2 routes, the analyzer uses a closed-form calculation to detect whether the direction has positive marginal edge and to estimate the optimal input size.

This makes V2/V2 evaluation fast and deterministic compared to routes involving V3.

### V2/V3

The first leg is quoted with V2 constant-product math.

The second leg is quoted through the Uniswap V3 Quoter.

Because V3 liquidity is concentrated and piecewise across ticks, the analyzer does not use a simple closed-form formula for the full route. Instead, it numerically searches for the input size that maximizes gross profit.

### V3/V2

The first leg is quoted through the Uniswap V3 Quoter.

The second leg is quoted with V2 constant-product math.

The route is optimized numerically because the V3 leg makes the full profit curve more complex than a pure V2/V2 route.

### V3/V3

Both legs are quoted through the Uniswap V3 Quoter.

The analyzer checks different Uniswap V3 fee-tier combinations, such as:

```text
fee=100  -> fee=500
fee=500  -> fee=3000
fee=3000 -> fee=100
```

The input amount is optimized numerically over a configured range.

---

## Optimizer

For routes involving V3, the analyzer uses numerical optimization to search for the input amount that maximizes:

```text
amount_out - amount_in
```

The number of iterations is controlled by:

```env
OPTIMIZER_ITERATIONS=70
```

Higher values usually improve search precision but increase runtime.

The search range is controlled by per-token upper bounds:

```text
WETH: 500
USDC: 1000000
USDT: 1000000
```

These values are not trade sizes. They are upper search bounds used by the optimizer.

For V3 routes, the optimizer should be interpreted as a practical numerical approximation rather than a formal proof of the global maximum across every possible tick configuration.

---

## Result Sorting

Results may be denominated in different starting tokens, such as WETH, USDC, or USDT.

To make block summaries easier to read, the analyzer sorts opportunities by an approximate USD-like gross value:

* Stablecoin-start routes are already treated as USD-like.
* WETH-start routes are converted approximately using the realized first-leg average price.

This sorting affects display order only.

The underlying route math still uses raw token units.

---

## Example Output

```text
==================================================
RESULT FOR BLOCK 25000051
==================================================
TOTAL OPPORTUNITIES: 12

Top opportunities (sorted by approximate USD-like gross profit):

------------------------------------------------------------------------------------------
ARBITRAGE FOUND
------------------------------------------------------------------------------------------
kind:         v3/v3
route:        WETH -> USDT -> WETH
pool A:       uniswap_v3 V3 fee=100 0xc7bBeC68d12a0d1830360F8Ec58fA599bA1b0e9b
pool B:       uniswap_v3 V3 fee=10000 0xC5aF84701f98Fa483eCe78aF83F11b6C38ACA71D
amount_in:    0.055779900656 WETH
amount_mid:   128.121098 USDT
amount_out:   0.055842969456 WETH
gross_profit: 0.0000630688 WETH
gross_profit_usd_approx: ~0.144863
profit_pct:   0.11306725%

Execution note:
These are gross opportunities only. Compare gross_profit with gas cost before treating them as executable.
For Ethereum mainnet, dust profits such as 1e-8 to 1e-6 WETH are usually not executable after gas.
```

---

## Configuration

Create a `.env` file in the project root:

```env
HTTP_ANVIL_RPC_URL=
HTTP_ARCHIVE_RPC_URL=
START_BLOCK=25000000
FINISH_BLOCK=25000020
DEBUG_ENABLED=False
OPTIMIZER_ITERATIONS=70
ABI_DIR=./abi
```

---

### Environment Variables

| Variable | Description |
| --- | --- |
| `HTTP_ANVIL_RPC_URL` | Local Anvil HTTP RPC endpoint used by the analyzer |
| `HTTP_ARCHIVE_RPC_URL` | Archive Ethereum RPC endpoint used as the Anvil fork source |
| `START_BLOCK` | First historical block to analyze |
| `FINISH_BLOCK` | Last historical block to analyze, inclusive |
| `DEBUG_ENABLED` | Enables detailed pool, route, and optimizer logs when set to `True` |
| `OPTIMIZER_ITERATIONS` | Number of iterations used by the numerical optimizer for V3-involving routes |
| `ABI_DIR` | Directory containing ABI JSON files |

---

## Requirements

Python dependencies are listed in:

```text
requirements.txt
```

Install them with:

```bash
pip install -r requirements.txt
```

The project expects a local Anvil node and an Ethereum archive RPC endpoint.

Tested infrastructure assumptions:

```text
Anvil: 1.5.0-stable
Archive node: Erigon archive node
```

---

## Run

Start the analyzer with:

```bash
python src/arbitrage_analyzer/main.py
```

After startup, the script prints configuration information, resets Anvil to each target block, discovers pools, evaluates arbitrage routes, and prints gross opportunities for each block.

---

## Debug Mode

Debug mode is controlled by:

```env
DEBUG_ENABLED=True
```

When enabled, the analyzer prints detailed internal information:

* Startup configuration
* Discovered V2 and V3 pools
* V2 reserves
* V3 liquidity, tick, and `sqrtPriceX96`
* Spot prices
* Route checks
* V2/V2 closed-form diagnostics
* Optimizer samples
* Optimizer iteration progress
* Amount in, intermediate amount, amount out, and profit for debug candidates

When disabled:

```env
DEBUG_ENABLED=False
```

The analyzer prints concise block-level summaries and the top detected opportunities.

---

## Design Decisions

### Historical fork instead of live execution

The analyzer is designed to inspect historical blockchain state, not to trade on live opportunities.

Using Anvil with an archive Erigon node makes it possible to reproduce past block state and evaluate whether mathematical arbitrage opportunities existed at that point in time.

### Gross profit first

The project intentionally separates opportunity discovery from execution analysis.

The scanner answers:

```text
Was there a mathematical price difference between pools at this historical block?
```

It does not answer:

```text
Could this be executed profitably after gas, priority fees, and MEV competition?
```

### V2 closed-form math

For V2/V2 routes, the constant-product model allows a closed-form optimal input calculation.

This makes the pure V2 route evaluation efficient and precise.

### V3 Quoter-based evaluation

For V3 routes, the analyzer uses Uniswap V3 Quoter v1 through historical `eth_call`.

This keeps the implementation focused on research pipeline design rather than reimplementing the complete Uniswap V3 tick-crossing swap engine in Python.

### No bundle or transaction simulation

The project intentionally avoids bundle simulation and transaction execution logic.

This keeps the scope limited to analytical detection of gross opportunities and makes the repository suitable as a portfolio case study for blockchain analytics, DeFi infrastructure, and MEV research.

---

## Use Cases

* Historical DEX arbitrage research
* DeFi market structure analysis
* Ethereum archive-node analytics
* AMM pricing study
* Uniswap V2/V3 behavior comparison
* Fork-based blockchain data engineering
* MEV research education
* Portfolio demonstration for Web3 infrastructure and DeFi analytics roles

---

## Limitations

This project is intentionally limited in scope.

It does not account for:

* Gas cost
* Base fee
* Priority fee
* Flash loan fees
* Flash swap mechanics
* ERC-20 approvals and transfer edge cases
* Router execution details
* Full transaction revert checks
* Bundle simulation
* Private relay behavior
* Builder-specific ordering
* Mempool competition
* State changes between block `N` and a hypothetical transaction in block `N + 1`

Because of these limitations, every detected opportunity should be interpreted as a gross mathematical signal, not as an executable trading opportunity.

---

## Why This Project Matters

DEX prices can diverge across pools because of liquidity fragmentation, different fee tiers, different trade histories, and different AMM designs.

This project shows how those differences can be detected historically by combining archive-node access, local forked state, ABI-based contract calls, AMM math, and route optimization.

It demonstrates the engineering foundation behind a research-grade MEV or DeFi analytics pipeline without implementing transaction execution or extraction logic.

The project is not a trading bot.

It is a technical case study in historical Ethereum state analysis and gross DEX arbitrage detection.

---

## Disclaimer

This project is for educational and analytical purposes only.

It does not provide financial advice, does not execute trades, and does not implement MEV extraction strategies.

---