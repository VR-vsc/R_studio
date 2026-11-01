"""Безопасные выражения RDL.

Синтаксис — подмножество Python + привычные `&&`, `||`, `!`, `true/false`:
    room_temp < target_temp - hysteresis && mode > 0
    1 if wet_for >= debounce else 0

Разрешены только: числа/строки/имена, арифметика, сравнения, and/or/not,
тернарный `a if c else b` и вызовы функций из белого списка FUNCS.
Никаких атрибутов, индексов, лямбд, импортов — eval не используется.
"""
from __future__ import annotations

import ast
import math
import operator
import random
import re
from typing import Any, Callable, Dict, Iterable, Optional, Set


class ExprError(ValueError):
    """Ошибка выражения с человеко-понятным сообщением."""


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _sign(x):
    return (x > 0) - (x < 0)


FUNCS: Dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "int": int,
    "float": float,
    "clamp": _clamp,
    "sign": _sign,
    "floor": math.floor,
    "ceil": math.ceil,
    "sqrt": lambda x: math.sqrt(max(0.0, x)),
    # rand() — подставляется рантаймом (детерминированный ГПСЧ устройства)
    "rand": None,
}

CONSTS = {"true": 1, "false": 0, "True": 1, "False": 0, "pi": math.pi}

# Имена, которые нельзя занять сигналом/переменной
RESERVED: Set[str] = set(FUNCS) | set(CONSTS) | {
    "dt", "t", "value", "and", "or", "not", "if", "else", "fw", "none", "null",
}

_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.Pow: operator.pow,
}
_CMP = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}

_BANG = re.compile(r"!(?!=)")


def normalize(src: str) -> str:
    """`&&`→and, `||`→or, `!x`→not x (кроме `!=`)."""
    s = src.replace("&&", " and ").replace("||", " or ")
    return _BANG.sub(" not ", s)


class Expr:
    """Скомпилированное (проверенное) выражение."""

    def __init__(self, src: str, tree: ast.Expression, names: Set[str]):
        self.src = src
        self.tree = tree
        self.names = names  # какие имена читает (для анализа зависимостей)

    def __call__(self, env: Dict[str, Any], rand: Optional[Callable[[], float]] = None) -> Any:
        return _eval(self.tree.body, env, rand or random.random)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Expr({self.src!r})"


def compile_expr(src: Any, known: Optional[Iterable[str]] = None) -> Expr:
    """Разобрать и проверить выражение. `known` — допустимые имена (None — не проверять)."""
    if isinstance(src, bool):
        src = "1" if src else "0"
    if isinstance(src, (int, float)):
        src = repr(src)
    if not isinstance(src, str) or not src.strip():
        raise ExprError("пустое выражение")
    if len(src) > 500:
        raise ExprError("выражение длиннее 500 символов")
    try:
        tree = ast.parse(normalize(src).strip(), mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"синтаксис: {exc.msg} (позиция {exc.offset})") from None
    names: Set[str] = set()
    _check(tree.body, names)
    if known is not None:
        allowed = set(known) | set(CONSTS) | {"dt", "t", "value"}
        unknown = sorted(n for n in names if n not in allowed)
        if unknown:
            raise ExprError("неизвестное имя: " + ", ".join(unknown))
    return Expr(src, tree, names)


def _check(node: ast.AST, names: Set[str]) -> None:
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, str, bool)) or node.value is None:
            raise ExprError("допустимы только числа и строки")
        return
    if isinstance(node, ast.Name):
        names.add(node.id)
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN:
            raise ExprError("недопустимая операция")
        _check(node.left, names)
        _check(node.right, names)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            raise ExprError("недопустимая унарная операция")
        _check(node.operand, names)
        return
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _check(v, names)
        return
    if isinstance(node, ast.Compare):
        if any(type(op) not in _CMP for op in node.ops):
            raise ExprError("допустимы сравнения ==, !=, <, <=, >, >=")
        _check(node.left, names)
        for c in node.comparators:
            _check(c, names)
        return
    if isinstance(node, ast.IfExp):
        _check(node.test, names)
        _check(node.body, names)
        _check(node.orelse, names)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
            fname = getattr(node.func, "id", "?")
            raise ExprError(f"функция '{fname}' не разрешена; есть: "
                            + ", ".join(sorted(FUNCS)))
        if node.keywords:
            raise ExprError("именованные аргументы не поддерживаются")
        for a in node.args:
            _check(a, names)
        return
    raise ExprError(f"конструкция {type(node).__name__} не поддерживается")


def _num(v):
    if isinstance(v, bool):
        return int(v)
    return v


def _eval(node: ast.AST, env: Dict[str, Any], rand: Callable[[], float]) -> Any:
    if isinstance(node, ast.Constant):
        return _num(node.value)
    if isinstance(node, ast.Name):
        if node.id in env:
            return _num(env[node.id])
        if node.id in CONSTS:
            return CONSTS[node.id]
        raise ExprError(f"нет значения для '{node.id}'")
    if isinstance(node, ast.BinOp):
        a = _eval(node.left, env, rand)
        b = _eval(node.right, env, rand)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
            return 0  # деление на ноль в физике устройства — мягко 0
        if isinstance(node.op, ast.Pow) and abs(b) > 10:
            raise ExprError("степень больше 10 запрещена")
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env, rand)
        if isinstance(node.op, ast.Not):
            return int(not v)
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            res = 1
            for v in node.values:
                res = _eval(v, env, rand)
                if not res:
                    return res
            return res
        res = 0
        for v in node.values:
            res = _eval(v, env, rand)
            if res:
                return res
        return res
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env, rand)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env, rand)
            if not _CMP[type(op)](left, right):
                return 0
            left = right
        return 1
    if isinstance(node, ast.IfExp):
        return _eval(node.body if _eval(node.test, env, rand) else node.orelse, env, rand)
    if isinstance(node, ast.Call):
        args = [_eval(a, env, rand) for a in node.args]
        name = node.func.id  # type: ignore[attr-defined]
        if name == "rand":
            return rand()
        try:
            return FUNCS[name](*args)
        except TypeError as exc:
            raise ExprError(f"{name}(): {exc}") from None
    raise ExprError(f"конструкция {type(node).__name__} не поддерживается")
