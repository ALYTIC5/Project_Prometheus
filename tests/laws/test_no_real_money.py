"""Law 5: no real money, ever, from code. Paper only.

CLAUDE.md is unambiguous — "No code in this repo may submit a real order.
There is no live broker adapter and you must not write one." Every other
law has a test; this one is the last to get one, and it gets a *static*
one, because the failure mode it guards against is a code path existing at
all, not a code path returning the wrong value.

The check is deliberately written before any broker code exists. That is
the point: it is a tripwire armed in advance, so the first commit that
imports a live-exchange SDK or defines an order-submission call outside
`prometheus/paper/` fails the build on the way in, rather than being
reviewed by whoever happens to read that diff. Unlike the four
`xfail(strict=True)` stubs for laws whose guarded code doesn't exist yet,
this check is real code that runs today and passes today.

Three things are asserted, over every `.py` file under `prometheus/`:

1. No module imports a live-broker / live-exchange trading SDK. There is
   no exemption for `prometheus/paper/` here — a paper broker is
   simulated in-process against recorded or simulated fills; it has no
   business holding an exchange client library at all.
2. No module calls a function named like an order submission
   (`create_order`, `submit_order`, `place_order`, `place_live_order`)
   outside `prometheus/paper/`. `paper/` is the only package that may
   eventually contain order-submission-shaped code, and even there Law 5
   binds it to simulation; this test does not attempt to prove
   paper-only-ness of `paper/` itself, only that live-order-shaped calls
   do not leak into the rest of the system.
3. No module binds a live-money-suggesting identifier (`LIVE_TRADING`,
   `PRODUCTION_BROKER`, `REAL_MONEY`, `LIVE_BROKER`, ...) to a truthy
   literal. Matching is on identifiers rather than raw file text so the
   check stays meaningful instead of tripping on prose in a docstring.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

PROMETHEUS_DIR = Path(__file__).resolve().parents[2] / "prometheus"
PAPER_DIR = PROMETHEUS_DIR / "paper"

# Root module names of client libraries whose primary purpose is talking to
# a live exchange or brokerage. Importing any of them anywhere in this repo
# is a Law 5 violation on its face.
_LIVE_BROKER_MODULES = frozenset(
    {
        "alpaca",
        "alpaca_trade_api",
        "binance",
        "bybit",
        "ccxt",
        "coinbase",
        "ib_insync",
        "ibapi",
        "kiteconnect",
        "krakenex",
        "MetaTrader5",
        "oandapyV20",
        "robin_stocks",
        "schwab",
        "tda",
        "tradier",
    }
)

# Function names that mean "send this to a venue". Allowed only under
# prometheus/paper/.
_ORDER_SUBMISSION_NAMES = frozenset(
    {"create_order", "submit_order", "place_order", "place_live_order"}
)

_LIVE_MONEY_NAME_RE = re.compile(
    r"(live[_-]?(trading|broker|order|money|account)"
    r"|production[_-]?broker"
    r"|real[_-]?money)",
    re.IGNORECASE,
)


def _python_files() -> list[Path]:
    return sorted(PROMETHEUS_DIR.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _called_name(node: ast.Call) -> str | None:
    """The bare function name of a call: `f()` -> "f", `a.b.f()` -> "f"."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _assigned_names(node: ast.AST) -> list[str]:
    """Names bound by an assignment-shaped node, ignoring subscripts."""
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign | ast.NamedExpr):
        targets = [node.target]
    else:
        return []

    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
        elif isinstance(target, ast.Tuple | ast.List):
            names.extend(el.id for el in target.elts if isinstance(el, ast.Name))
    return names


def _assigned_value(node: ast.AST) -> ast.expr | None:
    if isinstance(node, ast.Assign | ast.NamedExpr):
        return node.value
    if isinstance(node, ast.AnnAssign):
        return node.value
    return None


def test_no_module_imports_a_live_broker_sdk() -> None:
    offenders: list[str] = []
    for path in _python_files():
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            for root in roots:
                if root in _LIVE_BROKER_MODULES:
                    offenders.append(f"{path}: imports {root!r}")
    assert not offenders, (
        "LAW 5 VIOLATION: live-broker/exchange SDK imported. This repo is "
        f"paper-only and has no live broker adapter: {offenders}"
    )


def test_no_order_submission_calls_outside_paper() -> None:
    offenders: list[str] = []
    for path in _python_files():
        if path.is_relative_to(PAPER_DIR):
            continue  # paper/ may eventually hold order-shaped code — paper-only
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Call):
                name = _called_name(node)
                if name in _ORDER_SUBMISSION_NAMES:
                    offenders.append(f"{path}:{node.lineno}: calls {name}()")
    assert not offenders, (
        "LAW 5 VIOLATION: order-submission call outside prometheus/paper/. "
        f"No code in this repo may submit a real order: {offenders}"
    )


def test_no_live_money_flag_set_truthy() -> None:
    offenders: list[str] = []
    for path in _python_files():
        for node in ast.walk(_parse(path)):
            names = _assigned_names(node)
            if not names:
                continue
            value = _assigned_value(node)
            if not isinstance(value, ast.Constant) or not value.value:
                continue
            for name in names:
                if _LIVE_MONEY_NAME_RE.search(name):
                    offenders.append(f"{path}:{node.lineno}: {name} = {value.value!r}")
    assert not offenders, (
        "LAW 5 VIOLATION: a live-money identifier is bound to a truthy "
        f"literal. Paper only, always: {offenders}"
    )
