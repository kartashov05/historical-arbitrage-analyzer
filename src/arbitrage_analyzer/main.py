import itertools
from dotenv import load_dotenv
import os
from decimal import Decimal, getcontext
from functools import lru_cache
from web3 import Web3
from pprint import pprint

from abi_loader import load_abi


load_dotenv()
getcontext().prec = 90

def to_bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")

HTTP_ANVIL_RPC_URL = os.getenv("HTTP_ANVIL_RPC_URL")
HTTP_ARCHIVE_RPC_URL = os.getenv("HTTP_ARCHIVE_RPC_URL")
START_BLOCK = int(os.getenv("START_BLOCK"))
FINISH_BLOCK = int(os.getenv("FINISH_BLOCK"))
DEBUG_ENABLED = to_bool(os.getenv("DEBUG_ENABLED"))
OPTIMIZER_ITERATIONS = int(os.getenv("OPTIMIZER_ITERATIONS"))

BLOCK_IDENTIFIER = None
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Upper search bound for optimizer-based routes
MAX_INPUT_HUMAN = {
    "WETH": Decimal("500"),
    "USDC": Decimal("1000000"),
    "USDT": Decimal("1000000"),
}

# Minimum gross profit to show, in human units of token_start
MIN_PROFIT_HUMAN = {
    "WETH": Decimal("0"),
    "USDC": Decimal("0"),
    "USDT": Decimal("0"),
}

w3 = Web3(Web3.HTTPProvider(HTTP_ANVIL_RPC_URL))

TOKENS = {
    "WETH": Web3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
    "USDC": Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
    "USDT": Web3.to_checksum_address("0xdAC17F958D2ee523a2206206994597C13D831ec7"),
}

V2_FACTORIES = {
    "uniswap_v2": {
        "factory": Web3.to_checksum_address("0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"),
        "fee": Decimal("0.003"),
    },
    "sushiswap_v2": {
        "factory": Web3.to_checksum_address("0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"),
        "fee": Decimal("0.003"),
    },
    "pancakeswap_v2": {
        "factory": Web3.to_checksum_address("0x1097053Fd2ea711dad45caCcc45EfF7548fCB362"),
        "fee": Decimal("0.0025"),
    },
}

V3_FACTORIES = {
    "uniswap_v3": {
        "factory": Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984"),
        # Uniswap V3 Quoter v1
        # Works for quoteExactInputSingle(tokenIn, tokenOut, fee, amountIn, sqrtPriceLimitX96)
        "quoter": Web3.to_checksum_address("0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"),
        "quoter_version": "v1",
    },
}

V3_FACTORY_ADDRESS = V3_FACTORIES["uniswap_v3"]["factory"]
V3_QUOTER_ADDRESS = V3_FACTORIES["uniswap_v3"]["quoter"]

# Uniswap V3 fee tiers:
# 100   = 0.01%
# 500   = 0.05%
# 3000  = 0.30%
# 10000 = 1.00%
V3_FEES = [100, 500, 3000, 10000]

PAIRS = [
    ("WETH", "USDC"),
    ("WETH", "USDT"),
]

ERC20_ABI = load_abi("erc20")
V2_FACTORY_ABI = load_abi("uniswap_v2_factory")
V2_PAIR_ABI = load_abi("uniswap_v2_pool")
V3_FACTORY_ABI = load_abi("uniswap_v3_factory")
V3_POOL_ABI = load_abi("uniswap_v3_pool")
V3_QUOTER_ABI = load_abi("uniswap_v3_quoter")


def dbg(message=""):
    if DEBUG_ENABLED:
        print(message)


def sep(title=None):
    if DEBUG_ENABLED:
        print("\n" + "=" * 90)
        if title:
            print(title)
            print("=" * 90)


def checksum(address):
    return Web3.to_checksum_address(address)


def contract(address, abi):
    return w3.eth.contract(address=checksum(address), abi=abi)


def eth_call(fn):
    if BLOCK_IDENTIFIER is not None:
        return fn.call(block_identifier=BLOCK_IDENTIFIER)
    return fn.call()


@lru_cache(maxsize=None)
def get_decimals(token):
    c = contract(token, ERC20_ABI)
    return int(eth_call(c.functions.decimals()))


@lru_cache(maxsize=None)
def get_symbol(token):
    c = contract(token, ERC20_ABI)
    try:
        return eth_call(c.functions.symbol())
    except Exception:
        for sym, addr in TOKENS.items():
            if checksum(addr) == checksum(token):
                return sym
        return checksum(token)


def human_amount(raw_amount, decimals):
    return Decimal(int(raw_amount)) / (Decimal(10) ** int(decimals))


def raw_amount(human, decimals):
    return int(Decimal(str(human)) * (Decimal(10) ** int(decimals)))


def fmt_decimal(x, places=12):
    x = Decimal(x)

    if not x.is_finite():
        return str(x)

    if x == 0:
        return "0"

    abs_x = abs(x)

    # Fixed notation for ordinary values
    if Decimal("0.000001") <= abs_x < Decimal("1000000000000"):
        q = Decimal(1).scaleb(-places)
        s = format(x.quantize(q), "f")
        s = s.rstrip("0").rstrip(".")
        if s in ("", "-0"):
            return "0"
        return s

    # Scientific notation for very small / very large values
    s = f"{x:.{places}E}"
    mantissa, exp = s.split("E")
    mantissa = mantissa.rstrip("0").rstrip(".")
    exp_int = int(exp)
    return f"{mantissa}E{exp_int}"


def token_label(token):
    return get_symbol(checksum(token))


def pool_name(pool):
    if pool["type"] == "v2":
        return f'{pool["dex"]} V2 {pool["address"]}'

    if pool["type"] == "v3":
        return f'{pool["dex"]} V3 fee={pool["fee"]} {pool["address"]}'

    return str(pool)


def fee_to_decimal_from_v3_fee(fee):
    # V3 fee is in hundredths of a bip
    # 500 = 0.05% = 0.0005
    return Decimal(int(fee)) / Decimal("1000000")


def maybe_min_profit_raw(token):
    token = checksum(token)
    sym = token_label(token)
    decimals = get_decimals(token)
    return raw_amount(MIN_PROFIT_HUMAN.get(sym, Decimal("0")), decimals)


def get_v2_pair(factory_address, token_a, token_b):
    factory = contract(factory_address, V2_FACTORY_ABI)

    pair = eth_call(factory.functions.getPair(
        checksum(token_a),
        checksum(token_b)
    ))

    if pair == ZERO_ADDRESS:
        return None

    return checksum(pair)


def read_v2_pool(dex_name, factory_address, fee, token_a, token_b):
    pair_address = get_v2_pair(factory_address, token_a, token_b)

    if pair_address is None:
        dbg(f"[DISCOVER][V2] {dex_name}: pair not found")
        return None

    pair = contract(pair_address, V2_PAIR_ABI)

    token0 = checksum(eth_call(pair.functions.token0()))
    token1 = checksum(eth_call(pair.functions.token1()))
    reserve0, reserve1, _ = eth_call(pair.functions.getReserves())

    reserve0 = int(reserve0)
    reserve1 = int(reserve1)

    if reserve0 <= 0 or reserve1 <= 0:
        dbg(f"[DISCOVER][V2] {dex_name}: zero reserves, skip {pair_address}")
        return None

    pool = {
        "type": "v2",
        "dex": dex_name,
        "address": pair_address,
        "token0": token0,
        "token1": token1,
        "reserve0": reserve0,
        "reserve1": reserve1,
        "fee": Decimal(str(fee)),
    }

    dbg(f"[DISCOVER][V2] found {pool_name(pool)}")
    return pool


def discover_v2_pools(token_a, token_b):
    pools = []

    for dex_name, cfg in V2_FACTORIES.items():
        try:
            pool = read_v2_pool(
                dex_name=dex_name,
                factory_address=cfg["factory"],
                fee=cfg["fee"],
                token_a=token_a,
                token_b=token_b,
            )
            if pool is not None:
                pools.append(pool)
        except Exception as e:
            dbg(f"[WARN][V2] failed to read {dex_name}: {repr(e)}")

    return pools


def get_v3_pool(factory_address, token_a, token_b, fee):
    factory = contract(factory_address, V3_FACTORY_ABI)

    pool = eth_call(factory.functions.getPool(
        checksum(token_a),
        checksum(token_b),
        int(fee)
    ))

    if pool == ZERO_ADDRESS:
        return None

    return checksum(pool)


def read_v3_pool(dex_name, factory_address, quoter_address, token_a, token_b, fee):
    pool_address = get_v3_pool(factory_address, token_a, token_b, fee)

    if pool_address is None:
        dbg(f"[DISCOVER][V3] {dex_name} fee={fee}: pool not found")
        return None

    pool_contract = contract(pool_address, V3_POOL_ABI)

    token0 = checksum(eth_call(pool_contract.functions.token0()))
    token1 = checksum(eth_call(pool_contract.functions.token1()))
    liquidity = int(eth_call(pool_contract.functions.liquidity()))
    slot0 = eth_call(pool_contract.functions.slot0())

    sqrt_price_x96 = int(slot0[0])
    tick = int(slot0[1])

    if liquidity <= 0:
        dbg(f"[DISCOVER][V3] {dex_name} fee={fee}: zero active liquidity, skip {pool_address}")
        return None

    pool = {
        "type": "v3",
        "dex": dex_name,
        "factory": checksum(factory_address),
        "quoter": checksum(quoter_address),
        "address": pool_address,
        "token0": token0,
        "token1": token1,
        "fee": int(fee),
        "fee_decimal": fee_to_decimal_from_v3_fee(fee),
        "liquidity": liquidity,
        "sqrtPriceX96": sqrt_price_x96,
        "tick": tick,
    }

    dbg(f"[DISCOVER][V3] found {pool_name(pool)}")
    return pool


def discover_v3_pools(token_a, token_b):
    pools = []

    for dex_name, cfg in V3_FACTORIES.items():
        factory_address = cfg["factory"]
        quoter_address = cfg.get("quoter")

        if quoter_address is None:
            dbg(f"[WARN][V3] {dex_name}: no quoter configured, skip")
            continue

        if cfg.get("quoter_version", "v1") != "v1":
            dbg(f"[WARN][V3] {dex_name}: only Quoter v1 ABI is supported by this script, skip")
            continue

        for fee in V3_FEES:
            try:
                pool = read_v3_pool(
                    dex_name=dex_name,
                    factory_address=factory_address,
                    quoter_address=quoter_address,
                    token_a=token_a,
                    token_b=token_b,
                    fee=fee,
                )
                if pool is not None:
                    pools.append(pool)
            except Exception as e:
                dbg(f"[WARN][V3] failed to read {dex_name} fee={fee}: {repr(e)}")

    return pools


def discover_all_pools_for_pair(token_a, token_b):
    pools = []
    pools.extend(discover_v2_pools(token_a, token_b))
    pools.extend(discover_v3_pools(token_a, token_b))
    return pools


def v2_spot_price_token1_per_token0(pool):
    dec0 = get_decimals(pool["token0"])
    dec1 = get_decimals(pool["token1"])

    raw_price = Decimal(pool["reserve1"]) / Decimal(pool["reserve0"])
    human_price = raw_price * (Decimal(10) ** dec0) / (Decimal(10) ** dec1)
    return human_price


def v3_spot_price_token1_per_token0(pool):
    dec0 = get_decimals(pool["token0"])
    dec1 = get_decimals(pool["token1"])

    sqrt_p = Decimal(pool["sqrtPriceX96"]) / (Decimal(2) ** 96)
    raw_price = sqrt_p * sqrt_p
    human_price = raw_price * (Decimal(10) ** dec0) / (Decimal(10) ** dec1)
    return human_price


def print_pool_debug(pool):
    token0 = token_label(pool["token0"])
    token1 = token_label(pool["token1"])

    if pool["type"] == "v2":
        dec0 = get_decimals(pool["token0"])
        dec1 = get_decimals(pool["token1"])
        price = v2_spot_price_token1_per_token0(pool)

        dbg(f"\n[POOL][V2] {pool_name(pool)}")
        dbg(f"  token0/token1: {token0}/{token1}")
        dbg(f"  reserve0: {fmt_decimal(human_amount(pool['reserve0'], dec0), 8)} {token0}")
        dbg(f"  reserve1: {fmt_decimal(human_amount(pool['reserve1'], dec1), 8)} {token1}")
        dbg(f"  spot token1 per token0: {fmt_decimal(price, 12)} {token1}/{token0}")
        dbg(f"  fee: {pool['fee']}")

    elif pool["type"] == "v3":
        price = v3_spot_price_token1_per_token0(pool)

        dbg(f"\n[POOL][V3] {pool_name(pool)}")
        dbg(f"  token0/token1: {token0}/{token1}")
        dbg(f"  liquidity: {pool['liquidity']}")
        dbg(f"  sqrtPriceX96: {pool['sqrtPriceX96']}")
        dbg(f"  tick: {pool['tick']}")
        dbg(f"  spot token1 per token0: {fmt_decimal(price, 12)} {token1}/{token0}")
        dbg(f"  fee_decimal: {pool['fee_decimal']}")


def v2_amount_out(amount_in, reserve_in, reserve_out, fee):
    amount_in = Decimal(int(amount_in))
    reserve_in = Decimal(int(reserve_in))
    reserve_out = Decimal(int(reserve_out))
    fee = Decimal(str(fee))

    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0

    gamma = Decimal("1") - fee
    amount_in_with_fee = amount_in * gamma
    amount_out = amount_in_with_fee * reserve_out / (reserve_in + amount_in_with_fee)

    return int(amount_out)


def get_v2_reserves_for_direction(pool, token_in, token_out):
    token_in = checksum(token_in)
    token_out = checksum(token_out)

    if token_in == pool["token0"] and token_out == pool["token1"]:
        return pool["reserve0"], pool["reserve1"]

    if token_in == pool["token1"] and token_out == pool["token0"]:
        return pool["reserve1"], pool["reserve0"]

    raise ValueError("Tokens do not match V2 pool")


def quote_v2(pool, token_in, token_out, amount_in):
    reserve_in, reserve_out = get_v2_reserves_for_direction(
        pool=pool,
        token_in=token_in,
        token_out=token_out,
    )

    return v2_amount_out(
        amount_in=amount_in,
        reserve_in=reserve_in,
        reserve_out=reserve_out,
        fee=pool["fee"],
    )


# Cache V3 quotes because optimizer calls the same route many times
V3_QUOTE_CACHE = {}


def quote_v3(pool, token_in, token_out, amount_in):
    amount_in = int(amount_in)

    if amount_in <= 0:
        return 0

    token_in = checksum(token_in)
    token_out = checksum(token_out)

    if not (
        (token_in == pool["token0"] and token_out == pool["token1"])
        or
        (token_in == pool["token1"] and token_out == pool["token0"])
    ):
        raise ValueError("Tokens do not match V3 pool")

    quoter_address = checksum(pool.get("quoter", V3_QUOTER_ADDRESS))
    key = (pool["address"], quoter_address, token_in, token_out, int(pool["fee"]), amount_in, BLOCK_IDENTIFIER)
    cached = V3_QUOTE_CACHE.get(key)

    if cached is not None:
        return cached

    quoter = contract(quoter_address, V3_QUOTER_ABI)

    try:
        fn = quoter.functions.quoteExactInputSingle(
            token_in,
            token_out,
            int(pool["fee"]),
            amount_in,
            0
        )

        if BLOCK_IDENTIFIER is not None:
            amount_out = fn.call(block_identifier=BLOCK_IDENTIFIER)
        else:
            amount_out = fn.call()

        amount_out = int(amount_out)
        V3_QUOTE_CACHE[key] = amount_out
        return amount_out

    except Exception as e:
        if DEBUG_ENABLED:
            dbg(f"[QUOTE][V3][FAIL] {pool_name(pool)} {token_label(token_in)}->{token_label(token_out)} amount={amount_in}: {repr(e)}")
        V3_QUOTE_CACHE[key] = 0
        return 0


def quote(pool, token_in, token_out, amount_in):
    if int(amount_in) <= 0:
        return 0

    if pool["type"] == "v2":
        return quote_v2(pool, token_in, token_out, amount_in)

    if pool["type"] == "v3":
        return quote_v3(pool, token_in, token_out, amount_in)

    raise ValueError(f"Unsupported pool type: {pool['type']}")


def route_profit(pool_a, pool_b, token_start, token_mid, amount_in):
    amount_in = int(amount_in)

    if amount_in <= 0:
        return {
            "amount_mid": 0,
            "amount_out": 0,
            "profit": 0,
        }

    amount_mid = quote(
        pool=pool_a,
        token_in=token_start,
        token_out=token_mid,
        amount_in=amount_in,
    )

    if amount_mid <= 0:
        return {
            "amount_mid": 0,
            "amount_out": 0,
            "profit": -amount_in,
        }

    amount_out = quote(
        pool=pool_b,
        token_in=token_mid,
        token_out=token_start,
        amount_in=amount_mid,
    )

    profit = int(amount_out) - int(amount_in)

    return {
        "amount_mid": int(amount_mid),
        "amount_out": int(amount_out),
        "profit": int(profit),
    }


def print_route_profit_debug(pool_a, pool_b, token_start, token_mid, amount_in, label):
    token_start = checksum(token_start)
    token_mid = checksum(token_mid)

    start_dec = get_decimals(token_start)
    mid_dec = get_decimals(token_mid)

    result = route_profit(pool_a, pool_b, token_start, token_mid, amount_in)

    amount_in_h = human_amount(amount_in, start_dec)
    amount_mid_h = human_amount(result["amount_mid"], mid_dec)
    amount_out_h = human_amount(result["amount_out"], start_dec)
    profit_h = human_amount(result["profit"], start_dec)

    if amount_in > 0:
        profit_pct = Decimal(result["profit"]) / Decimal(amount_in) * Decimal("100")
    else:
        profit_pct = Decimal("0")

    dbg(f"    [{label}]")
    dbg(f"      amount_in:  {fmt_decimal(amount_in_h, 12)} {token_label(token_start)}")
    dbg(f"      amount_mid: {fmt_decimal(amount_mid_h, 6)} {token_label(token_mid)}")
    dbg(f"      amount_out: {fmt_decimal(amount_out_h, 12)} {token_label(token_start)}")
    dbg(f"      profit:     {fmt_decimal(profit_h, 12)} {token_label(token_start)} ({fmt_decimal(profit_pct, 8)}%)")

    return result


# V2/V2 closed-form math
def v2_v2_closed_form_debug(pool_a, pool_b, token_start, token_mid):
    reserve_in_a, reserve_out_a = get_v2_reserves_for_direction(
        pool=pool_a,
        token_in=token_start,
        token_out=token_mid,
    )

    reserve_in_b, reserve_out_b = get_v2_reserves_for_direction(
        pool=pool_b,
        token_in=token_mid,
        token_out=token_start,
    )

    x_a = Decimal(reserve_in_a)
    y_a = Decimal(reserve_out_a)

    y_b = Decimal(reserve_in_b)
    x_b = Decimal(reserve_out_b)

    gamma_a = Decimal("1") - Decimal(pool_a["fee"])
    gamma_b = Decimal("1") - Decimal(pool_b["fee"])

    c = gamma_a * gamma_b * x_b * y_a
    d = x_a * y_b
    e = gamma_a * (y_b + gamma_b * y_a)

    marginal_factor = c / d if d > 0 else Decimal("0")

    if c <= d:
        return {
            "profitable_marginal": False,
            "marginal_factor": marginal_factor,
            "amount_in_optimal": 0,
            "amount_in_breakeven": 0,
            "c": c,
            "d": d,
            "e": e,
            "reserves": {
                "reserve_in_a": reserve_in_a,
                "reserve_out_a": reserve_out_a,
                "reserve_in_b": reserve_in_b,
                "reserve_out_b": reserve_out_b,
            }
        }

    amount_in_optimal = ((c * d).sqrt() - d) / e
    amount_in_breakeven = (c - d) / e

    if amount_in_optimal <= 0:
        amount_in_optimal = Decimal(0)

    if amount_in_breakeven <= 0:
        amount_in_breakeven = Decimal(0)

    return {
        "profitable_marginal": True,
        "marginal_factor": marginal_factor,
        "amount_in_optimal": int(amount_in_optimal),
        "amount_in_breakeven": int(amount_in_breakeven),
        "c": c,
        "d": d,
        "e": e,
        "reserves": {
            "reserve_in_a": reserve_in_a,
            "reserve_out_a": reserve_out_a,
            "reserve_in_b": reserve_in_b,
            "reserve_out_b": reserve_out_b,
        }
    }


def debug_v2_v2_math(pool_a, pool_b, token_start, token_mid, cf):
    if not(DEBUG_ENABLED):
        return

    start_dec = get_decimals(token_start)

    dbg("  [V2/V2 closed-form debug]")
    dbg(f"    route: {token_label(token_start)} -> {token_label(token_mid)} -> {token_label(token_start)}")
    dbg(f"    pool_a: {pool_name(pool_a)}")
    dbg(f"    pool_b: {pool_name(pool_b)}")
    dbg(f"    reserve_in_a:  {cf['reserves']['reserve_in_a']}")
    dbg(f"    reserve_out_a: {cf['reserves']['reserve_out_a']}")
    dbg(f"    reserve_in_b:  {cf['reserves']['reserve_in_b']}")
    dbg(f"    reserve_out_b: {cf['reserves']['reserve_out_b']}")
    dbg(f"    c = gamma_a * gamma_b * x_b * y_a: {fmt_decimal(cf['c'], 4)}")
    dbg(f"    d = x_a * y_b:                       {fmt_decimal(cf['d'], 4)}")
    dbg(f"    marginal_factor c/d:                 {fmt_decimal(cf['marginal_factor'], 12)}")
    dbg(f"    marginal edge after fees:             {fmt_decimal((cf['marginal_factor'] - Decimal(1)) * Decimal(100), 8)}%")

    if not cf["profitable_marginal"]:
        dbg("    result: no profitable infinitesimal trade in this direction")
        return

    opt_h = human_amount(cf["amount_in_optimal"], start_dec)
    be_h = human_amount(cf["amount_in_breakeven"], start_dec)

    dbg(f"    amount_in_optimal:                   {fmt_decimal(opt_h, 12)} {token_label(token_start)}")
    dbg(f"    amount_in_breakeven:                 {fmt_decimal(be_h, 12)} {token_label(token_start)}")

    opt = cf["amount_in_optimal"]
    be = cf["amount_in_breakeven"]

    # Sanity checks around the optimum and breakeven
    candidates = [
        ("0.25x optimal", opt // 4),
        ("0.50x optimal", opt // 2),
        ("1.00x optimal", opt),
        ("1.50x optimal", int(Decimal(opt) * Decimal("1.5"))),
        ("0.90x breakeven", int(Decimal(be) * Decimal("0.9"))),
        ("1.00x breakeven", be),
    ]

    for label, amount in candidates:
        if amount > 0:
            print_route_profit_debug(pool_a, pool_b, token_start, token_mid, amount, label)


def check_v2_v2(pool_a, pool_b, token_start, token_mid):
    cf = v2_v2_closed_form_debug(pool_a, pool_b, token_start, token_mid)

    debug_v2_v2_math(pool_a, pool_b, token_start, token_mid, cf)

    amount_in = int(cf["amount_in_optimal"])

    if amount_in <= 0:
        return None

    result = route_profit(
        pool_a=pool_a,
        pool_b=pool_b,
        token_start=token_start,
        token_mid=token_mid,
        amount_in=amount_in,
    )

    if result["profit"] <= maybe_min_profit_raw(token_start):
        return None

    return {
        "kind": "v2/v2",
        "pool_a": pool_a,
        "pool_b": pool_b,
        "token_start": checksum(token_start),
        "token_mid": checksum(token_mid),
        "amount_in": amount_in,
        "amount_mid": result["amount_mid"],
        "amount_out": result["amount_out"],
        "profit": result["profit"],
        "debug": {
            "amount_in_breakeven": cf["amount_in_breakeven"],
            "marginal_factor": cf["marginal_factor"],
        }
    }


# Optimizer for V2/V3, V3/V2, V3/V3
def get_optimizer_right_bound(token_start):
    token_start = checksum(token_start)
    sym = token_label(token_start)
    decimals = get_decimals(token_start)

    human = MAX_INPUT_HUMAN.get(sym)
    if human is None:
        raise ValueError(f"No MAX_INPUT_HUMAN configured for {sym}")

    return raw_amount(human, decimals)


def sample_route_before_optimization(pool_a, pool_b, token_start, token_mid, right):
    if not(DEBUG_ENABLED):
        return

    dbg("  [optimizer precheck samples]")

    samples = [
        ("very small", right // 100000),
        ("small", right // 10000),
        ("medium", right // 1000),
        ("large", right // 100),
    ]

    for label, amount in samples:
        if amount > 0:
            print_route_profit_debug(pool_a, pool_b, token_start, token_mid, amount, label)


def ternary_search_optimal_amount(
    pool_a,
    pool_b,
    token_start,
    token_mid,
    left,
    right,
    iterations=70,
):
    left = int(left)
    right = int(right)

    if right <= left:
        return None

    best_amount = 0
    best_result = None

    for i in range(iterations):
        if right - left <= 3:
            break

        m1 = left + (right - left) // 3
        m2 = right - (right - left) // 3

        if m1 <= 0 or m2 <= 0 or m1 == m2:
            break

        r1 = route_profit(pool_a, pool_b, token_start, token_mid, m1)
        r2 = route_profit(pool_a, pool_b, token_start, token_mid, m2)

        p1 = r1["profit"]
        p2 = r2["profit"]

        if best_result is None or p1 > best_result["profit"]:
            best_amount = m1
            best_result = r1

        if best_result is None or p2 > best_result["profit"]:
            best_amount = m2
            best_result = r2

        if DEBUG_ENABLED and (i % 10 == 0 or i == iterations - 1):
            start_dec = get_decimals(token_start)
            dbg(f"    [optimizer iter={i}]")
            dbg(f"      left={fmt_decimal(human_amount(left, start_dec), 8)} right={fmt_decimal(human_amount(right, start_dec), 8)} {token_label(token_start)}")
            dbg(f"      m1={fmt_decimal(human_amount(m1, start_dec), 8)} profit1={fmt_decimal(human_amount(p1, start_dec), 12)}")
            dbg(f"      m2={fmt_decimal(human_amount(m2, start_dec), 8)} profit2={fmt_decimal(human_amount(p2, start_dec), 12)}")

        if p1 < p2:
            left = m1
        else:
            right = m2

    # Final local candidates
    candidates = set([
        best_amount,
        left,
        right,
        (left + right) // 2,
        left + (right - left) // 4,
        right - (right - left) // 4,
    ])

    # Add nearby integer amounts if interval is small
    for x in list(candidates):
        for delta in [-3, -2, -1, 1, 2, 3]:
            y = x + delta
            if y > 0:
                candidates.add(y)

    final_best_amount = 0
    final_best_result = None

    for amount in candidates:
        if amount <= 0:
            continue

        result = route_profit(pool_a, pool_b, token_start, token_mid, amount)

        if final_best_result is None or result["profit"] > final_best_result["profit"]:
            final_best_amount = amount
            final_best_result = result

    if final_best_result is None:
        return None

    return {
        "amount_in": int(final_best_amount),
        "amount_mid": int(final_best_result["amount_mid"]),
        "amount_out": int(final_best_result["amount_out"]),
        "profit": int(final_best_result["profit"]),
    }


def debug_optimizer_result(pool_a, pool_b, token_start, token_mid, result):
    if (not(DEBUG_ENABLED)) or result is None:
        return

    opt = int(result["amount_in"])

    dbg("  [optimizer result check]")
    dbg(f"    best amount raw: {opt}")

    candidates = [
        ("0.25x optimal", opt // 4),
        ("0.50x optimal", opt // 2),
        ("1.00x optimal", opt),
        ("1.50x optimal", int(Decimal(opt) * Decimal("1.5"))),
        ("2.00x optimal", opt * 2),
    ]

    for label, amount in candidates:
        if amount > 0:
            print_route_profit_debug(pool_a, pool_b, token_start, token_mid, amount, label)


def check_with_optimizer(pool_a, pool_b, token_start, token_mid):
    right = get_optimizer_right_bound(token_start)

    dbg("  [optimizer route]")
    dbg(f"    kind: {pool_a['type']}/{pool_b['type']}")
    dbg(f"    route: {token_label(token_start)} -> {token_label(token_mid)} -> {token_label(token_start)}")
    dbg(f"    pool_a: {pool_name(pool_a)}")
    dbg(f"    pool_b: {pool_name(pool_b)}")
    dbg(f"    right bound: {fmt_decimal(human_amount(right, get_decimals(token_start)), 8)} {token_label(token_start)}")

    sample_route_before_optimization(pool_a, pool_b, token_start, token_mid, right)

    result = ternary_search_optimal_amount(
        pool_a=pool_a,
        pool_b=pool_b,
        token_start=token_start,
        token_mid=token_mid,
        left=1,
        right=right,
        iterations=OPTIMIZER_ITERATIONS,
    )

    debug_optimizer_result(pool_a, pool_b, token_start, token_mid, result)

    if result is None:
        return None

    if result["profit"] <= maybe_min_profit_raw(token_start):
        return None

    return {
        "kind": f'{pool_a["type"]}/{pool_b["type"]}',
        "pool_a": pool_a,
        "pool_b": pool_b,
        "token_start": checksum(token_start),
        "token_mid": checksum(token_mid),
        "amount_in": result["amount_in"],
        "amount_mid": result["amount_mid"],
        "amount_out": result["amount_out"],
        "profit": result["profit"],
    }


def check_direction(pool_a, pool_b, token_start, token_mid):
    dbg(f"\n[CHECK] {pool_a['type']}/{pool_b['type']} | {token_label(token_start)} -> {token_label(token_mid)} -> {token_label(token_start)}")
    dbg(f"  A: {pool_name(pool_a)}")
    dbg(f"  B: {pool_name(pool_b)}")

    if pool_a["type"] == "v2" and pool_b["type"] == "v2":
        return check_v2_v2(pool_a, pool_b, token_start, token_mid)

    return check_with_optimizer(pool_a, pool_b, token_start, token_mid)


def check_two_pools(pool_a, pool_b, token_a, token_b):
    opportunities = []

    # Check all economically distinct two-hop cycles:
    # token_a -> token_b -> token_a and token_b -> token_a -> token_b
    # each in both pool orders
    route_specs = [
        ("pool_a first, start token_a", pool_a, pool_b, token_a, token_b),
        ("pool_b first, start token_a", pool_b, pool_a, token_a, token_b),
        ("pool_a first, start token_b", pool_a, pool_b, token_b, token_a),
        ("pool_b first, start token_b", pool_b, pool_a, token_b, token_a),
    ]

    for label, first_pool, second_pool, token_start, token_mid in route_specs:
        try:
            result = check_direction(
                pool_a=first_pool,
                pool_b=second_pool,
                token_start=token_start,
                token_mid=token_mid,
            )
            if result is not None:
                opportunities.append(result)
        except Exception as e:
            dbg(f"[WARN] direction failed {label}: {repr(e)}")

    return opportunities


def scan_pair(token_a_symbol, token_b_symbol):
    token_a = TOKENS[token_a_symbol]
    token_b = TOKENS[token_b_symbol]

    sep(f"SCAN PAIR {token_a_symbol}/{token_b_symbol}")

    pools = discover_all_pools_for_pair(token_a, token_b)

    dbg(f"\n[DISCOVER] total pools found: {len(pools)}")

    for pool in pools:
        print_pool_debug(pool)

    opportunities = []

    for pool_a, pool_b in itertools.combinations(pools, 2):
        results = check_two_pools(
            pool_a=pool_a,
            pool_b=pool_b,
            token_a=token_a,
            token_b=token_b,
        )
        opportunities.extend(results)

    opportunities.sort(key=opportunity_sort_key, reverse=True)

    sep(f"RESULTS FOR {token_a_symbol}/{token_b_symbol}")
    dbg(f"opportunities found: {len(opportunities)}")

    if DEBUG_ENABLED:
        for op in opportunities[:10]:
            print_opportunity(op)

    return opportunities


STABLE_TOKEN_SYMBOLS = {"USDC", "USDT"}


def profit_human_value(op):
    token_start = checksum(op["token_start"])
    start_decimals = get_decimals(token_start)
    return human_amount(op["profit"], start_decimals)


def estimate_profit_usd(op):
    """
        Approximate ranking value in USD-like units

        This is only for sorting/display. Execution math still uses raw token units
        For stablecoin-start routes, profit is already USD-like. For WETH-start
        WETH/stable routes, use the realized first-leg average price as a simple
        local conversion proxy
    """
    token_start = checksum(op["token_start"])
    token_mid = checksum(op["token_mid"])
    start_sym = token_label(token_start)
    mid_sym = token_label(token_mid)

    profit_h = profit_human_value(op)

    if start_sym in STABLE_TOKEN_SYMBOLS:
        return profit_h

    if start_sym == "WETH" and mid_sym in STABLE_TOKEN_SYMBOLS:
        start_decimals = get_decimals(token_start)
        mid_decimals = get_decimals(token_mid)
        amount_in_h = human_amount(op["amount_in"], start_decimals)
        amount_mid_h = human_amount(op["amount_mid"], mid_decimals)

        if amount_in_h > 0 and amount_mid_h > 0:
            return profit_h * (amount_mid_h / amount_in_h)

    return profit_h


def opportunity_sort_key(op):
    return (estimate_profit_usd(op), profit_human_value(op))


def print_opportunity(op):
    token_start = checksum(op["token_start"])
    token_mid = checksum(op["token_mid"])

    start_decimals = get_decimals(token_start)
    mid_decimals = get_decimals(token_mid)

    amount_in_h = human_amount(op["amount_in"], start_decimals)
    amount_mid_h = human_amount(op["amount_mid"], mid_decimals)
    amount_out_h = human_amount(op["amount_out"], start_decimals)
    profit_h = human_amount(op["profit"], start_decimals)
    profit_pct = Decimal(op["profit"]) / Decimal(op["amount_in"]) * Decimal("100")

    print("\n" + "-" * 90)
    print("ARBITRAGE FOUND")
    print("-" * 90)
    print("kind:        ", op["kind"])
    print("route:       ", f"{token_label(token_start)} -> {token_label(token_mid)} -> {token_label(token_start)}")
    print("pool A:      ", pool_name(op["pool_a"]))
    print("pool B:      ", pool_name(op["pool_b"]))
    print("amount_in:   ", f"{fmt_decimal(amount_in_h, 12)} {token_label(token_start)}")
    print("amount_mid:  ", f"{fmt_decimal(amount_mid_h, 6)} {token_label(token_mid)}")
    print("amount_out:  ", f"{fmt_decimal(amount_out_h, 12)} {token_label(token_start)}")
    print("gross_profit:", f"{fmt_decimal(profit_h, 12)} {token_label(token_start)}")
    print("gross_profit_usd_approx:", f"~{fmt_decimal(estimate_profit_usd(op), 6)}")
    print("profit_pct:  ", f"{fmt_decimal(profit_pct, 8)}%")

    if op.get("debug", {}).get("amount_in_breakeven") is not None:
        be_h = human_amount(op["debug"]["amount_in_breakeven"], start_decimals)
        print("breakeven_in:", f"{fmt_decimal(be_h, 12)} {token_label(token_start)}")

    if op.get("debug", {}).get("marginal_factor") is not None:
        mf = op["debug"]["marginal_factor"]
        edge = (Decimal(mf) - Decimal(1)) * Decimal(100)
        print("marginal_edge_after_fees:", f"{fmt_decimal(edge, 8)}%")


def ensure_connected():
    if not w3.is_connected():
        raise RuntimeError(f"Web3 is not connected. Check RPC_URL: {HTTP_ANVIL_RPC_URL}")


def print_startup_info():
    sep("STARTUP")

    print(f"HTTP_ANVIL_RPC_URL: {HTTP_ANVIL_RPC_URL}")
    print(f"connected: {w3.is_connected()}")

    ensure_connected()

    latest = w3.eth.block_number
    print(f"current RPC block: {latest}")
    print(f"START_BLOCK: {START_BLOCK}")
    print(f"FINISH_BLOCK: {FINISH_BLOCK}")
    print(f"DEBUG_ENABLED: {DEBUG_ENABLED}")
    print(f"OPTIMIZER_ITERATIONS: {OPTIMIZER_ITERATIONS}")

    print("\nConfigured pairs:")
    for a, b in PAIRS:
        print(f"  {a}/{b}")

    print("\nConfigured max optimizer bounds:")
    for sym, value in MAX_INPUT_HUMAN.items():
        print(f"  {sym}: {value}")


def print_final_summary(all_opportunities, block_number):
    print("\n" + "=" * 50)
    print(f"RESULT FOR BLOCK {block_number}")
    print("=" * 50)
    print(f"TOTAL OPPORTUNITIES: {len(all_opportunities)}")

    if not all_opportunities:
        print("No profitable opportunities found with current settings.")

        if DEBUG_ENABLED:
            print("\nDebug checklist:")
            print("1. Confirm START_BLOCK / FINISH_BLOCK point to the intended historical range.")
            print("2. Confirm your RPC has archive access for these blocks, or Anvil is forked correctly.")
            print("3. Confirm V2 pools have non-zero reserves.")
            print("4. Confirm V3 Quoter exists at this block.")
            print("5. Try larger MAX_INPUT_HUMAN values if the optimum may be outside the search bound.")
            print("6. Try smaller MIN_PROFIT_HUMAN filters if you changed them.")
        return

    print("\nTop opportunities (sorted by approximate USD-like gross profit):")
    for op in all_opportunities[:10]:
        print_opportunity(op)

    print("\nExecution note:")
    print("These are gross opportunities only. Compare gross_profit with gas cost before treating them as executable.")
    print("For Ethereum mainnet, dust profits such as 1e-8 to 1e-6 WETH are usually not executable after gas.")


def validate_block_range():
    if int(START_BLOCK) <= 0:
        raise ValueError("START_BLOCK must be a positive integer")

    if int(FINISH_BLOCK) <= 0:
        raise ValueError("FINISH_BLOCK must be a positive integer")

    if int(START_BLOCK) > int(FINISH_BLOCK):
        raise ValueError("START_BLOCK must be less than or equal to FINISH_BLOCK")


def reset_block_cache():
    V3_QUOTE_CACHE.clear()


def scan_block(block_number):
    global BLOCK_IDENTIFIER

    BLOCK_IDENTIFIER = int(block_number)
    reset_block_cache()

    if DEBUG_ENABLED:
        sep(f"BLOCK {BLOCK_IDENTIFIER}")
        dbg(f"BLOCK_IDENTIFIER: {BLOCK_IDENTIFIER}")
        dbg("mode: historical eth_call mode")

    all_opportunities = []

    for token_a_symbol, token_b_symbol in PAIRS:
        opportunities = scan_pair(token_a_symbol, token_b_symbol)
        all_opportunities.extend(opportunities)

    all_opportunities.sort(key=opportunity_sort_key, reverse=True)

    print_final_summary(all_opportunities, BLOCK_IDENTIFIER)

    return all_opportunities


def reset_anvil_to_block(w3: Web3, block_number: int) -> bool:
    resp = w3.provider.make_request(
        "anvil_reset",
        [
            {
                "forking": {
                    "jsonRpcUrl": HTTP_ARCHIVE_RPC_URL,
                    "blockNumber": block_number,
                }
            }
        ],
    )

    if "error" in resp:
        print(f"[anvil_reset error] block={block_number}")
        pprint(resp["error"])
        print("-" * 70)
        return False

    try:
        latest_after_reset = int(w3.eth.block_number)
        if latest_after_reset != int(block_number):
            print(
                f"[anvil_reset warning] requested fork block {block_number}, "
                f"but Anvil latest is {latest_after_reset}. Historical eth_call will still use "
                f"block_identifier={block_number}; verify your fork/RPC setup if calls fail"
            )
    except Exception as e:
        print(f"[anvil_reset warning] could not verify latest block after reset: {repr(e)}")

    return True


def main():
    ensure_connected()
    validate_block_range()
    print_startup_info()

    for block_number in range(START_BLOCK, FINISH_BLOCK + 1):
        ok = reset_anvil_to_block(w3, block_number)
        if not ok:
            continue

        scan_block(block_number)


if __name__ == "__main__":
    main()