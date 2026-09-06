"""Law 5: no real money, ever, from code. Paper only.

CLAUDE.md is unambiguous — "No code in this repo may submit a real order.
There is no live broker adapter and you must not write one." Every other
law has a test; this one is the last to get one, and it gets a *static*
one, because the failure mode it guards against is a code path existing at
all, not a code path returning the wrong value.

The check is deliberately written before any broker code exists. That is
the point: it is a tripwire armed in advance, so the first commit that
defines an order-submission call outside `prometheus/paper/` fails the
build on the way in, rather than being reviewed by whoever happens to
read that diff. Unlike the four `xfail(strict=True)` stubs for laws
whose guarded code doesn't exist yet, this check is real code that runs
today and passes today.

Two things are asserted, over every `.py` file under `prometheus/`:

1. No module calls a function named like an order submission
   (`create_order`, `submit_order`, `place_order`, `place_live_order`)
   outside `prometheus/paper/`. `paper/` is the only package that may
   eventually contain order-submission-shaped code, and even there Law 5
   binds it to simulation; this test does not attempt to prove
   paper-only-ness of `paper/` itself, only that live-order-shaped calls
   do not leak into the rest of the system.
2. No module binds a live-money-suggesting identifier (`LIVE_TRADING`,
   `PRODUCTION_BROKER`, `REAL_MONEY`, `LIVE_BROKER`, ...) to a truthy
   literal. Matching is on identifiers rather than raw file text so the
   check stays meaningful instead of tripping on prose in a docstring.

An earlier version of this test also blanket-banned importing any
live-exchange SDK (ccxt, binance, ...) anywhere under `prometheus/`. That
check measured the wrong thing: Law 5 is about submitting real orders,
not about which library is imported, and the same SDKs this repo needs
for read-only public market data (PROMPT 1's `data/ingestion.py`) and
for paper-trading (PROMPT 7's testnet/sandbox adapter) are the only
realistic clients for those exchanges. A blanket import ban cannot
coexist with the project's own architecture, so it was removed —
order-submission detection (check 1) is the actual enforcement
mechanism for "no real money, ever, from code."
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

PROMETHEUS_DIR = Path(__file__).resolve().parents[2] / "prometheus"
PAPER_DIR = PROMETHEUS_DIR / "paper"

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
