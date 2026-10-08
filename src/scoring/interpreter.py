"""Tiny evaluator for the per-field scoring formulas stored in model.json.

Each formula is a template string with a single placeholder ``{v}`` for the
raw input value, using a small Excel-like vocabulary: IF, IFS, CHOOSE,
MATCH, LOWER, YEAR, YEARFRAC, TODAY, comparisons, and TRUE as a catch-all.
This is not a general spreadsheet engine -- it only implements the handful
of constructs that actually appear in model.json.
"""

from __future__ import annotations

import datetime as _dt
import re


def _today() -> _dt.date:
    return _dt.date.today()


def _year(value) -> int:
    if isinstance(value, _dt.date):
        return value.year
    return int(value)


def _yearfrac(start, end) -> float:
    if isinstance(start, str):
        start = _dt.date.fromisoformat(start)
    if isinstance(end, str):
        end = _dt.date.fromisoformat(end)
    return (end - start).days / 365.25


class _Tokenizer:
    _TOKEN_RE = re.compile(
        r"""
        \s*(?:
            (?P<num>\d+\.\d+|\.\d+|\d+)
          | (?P<str>"[^"]*")
          | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
          | (?P<op><=|>=|<>|=|<|>|,|\(|\)|\{|\}|\+|-|\*|/)
        )
        """,
        re.VERBOSE,
    )

    def __init__(self, text: str):
        self.tokens: list[tuple[str, str]] = []
        pos = 0
        while pos < len(text):
            if text[pos].isspace():
                pos += 1
                continue
            m = self._TOKEN_RE.match(text, pos)
            if not m or m.end() == pos:
                raise ValueError(f"cannot tokenize formula at: {text[pos:pos + 20]!r}")
            kind = m.lastgroup
            value = m.group(kind)
            self.tokens.append((kind, value))
            pos = m.end()
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def next(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def expect(self, value):
        kind, tok_value = self.next()
        if tok_value != value:
            raise ValueError(f"expected {value!r}, got {tok_value!r}")


class FormulaError(Exception):
    pass


def _parse_args(tz: _Tokenizer, env):
    args = []
    if tz.peek()[1] == ")":
        return args
    args.append(_parse_expr(tz, env))
    while tz.peek()[1] == ",":
        tz.next()
        args.append(_parse_expr(tz, env))
    return args


def _parse_list(tz: _Tokenizer):
    tz.expect("{")
    items = []
    if tz.peek()[1] != "}":
        while True:
            kind, value = tz.next()
            if kind != "str":
                raise ValueError(f"expected string literal in list, got {value!r}")
            items.append(value[1:-1])
            if tz.peek()[1] == ",":
                tz.next()
                continue
            break
    tz.expect("}")
    return items


_FUNCS = {}


def _call(name, args):
    name = name.upper()
    if name == "IF":
        cond, then, els = args
        return then if cond else els
    if name == "IFS":
        if len(args) % 2 != 0:
            raise FormulaError("IFS needs an even number of arguments")
        for i in range(0, len(args), 2):
            if args[i]:
                return args[i + 1]
        raise FormulaError("IFS: no condition matched")
    if name == "LOWER":
        (s,) = args
        return str(s).lower()
    if name == "YEAR":
        (v,) = args
        return _year(v)
    if name == "YEARFRAC":
        start, end = args
        return _yearfrac(start, end)
    if name == "TODAY":
        return _today()
    if name == "TRUE":
        return True
    if name == "MAX":
        return max(args)
    if name == "MIN":
        return min(args)
    raise FormulaError(f"unsupported function: {name}")


def _parse_primary(tz: _Tokenizer, env):
    kind, value = tz.peek()
    if value == "(":
        tz.next()
        v = _parse_expr(tz, env)
        tz.expect(")")
        return v
    if value == "{":
        return _parse_list(tz)
    if kind == "num":
        tz.next()
        return float(value) if ("." in value) else int(value)
    if kind == "str":
        tz.next()
        return value[1:-1]
    if kind == "ident":
        tz.next()
        name = value
        if name == "TRUE":
            if tz.peek()[1] == "(":
                tz.next()
                tz.expect(")")
            return True
        if tz.peek()[1] == "(":
            tz.next()
            if name.upper() == "MATCH":
                needle = _parse_expr(tz, env)
                tz.expect(",")
                haystack = _parse_list(tz) if tz.peek()[1] == "{" else _parse_expr(tz, env)
                tz.expect(",")
                _ = _parse_expr(tz, env)  # match-type, always exact here
                tz.expect(")")
                try:
                    return haystack.index(needle) + 1
                except ValueError:
                    raise FormulaError(f"MATCH: {needle!r} not found in {haystack!r}")
            if name.upper() == "CHOOSE":
                tz.next() if False else None
                idx = _parse_expr(tz, env)
                choices = []
                while tz.peek()[1] == ",":
                    tz.next()
                    choices.append(_parse_expr(tz, env))
                tz.expect(")")
                return choices[int(idx) - 1]
            args = _parse_args(tz, env)
            tz.expect(")")
            return _call(name, args)
        if name == "v":
            return env["v"]
        raise FormulaError(f"unknown identifier: {name}")
    raise FormulaError(f"unexpected token: {value!r}")


_COMPARE_OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<>": lambda a, b: a != b,
    "=": lambda a, b: a == b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
}


def _parse_unary(tz: _Tokenizer, env):
    if tz.peek()[1] == "-":
        tz.next()
        return -_parse_unary(tz, env)
    return _parse_primary(tz, env)


def _parse_term(tz: _Tokenizer, env):
    left = _parse_unary(tz, env)
    while tz.peek()[1] in ("*", "/"):
        _, op = tz.next()
        right = _parse_unary(tz, env)
        left = left * right if op == "*" else left / right
    return left


def _parse_additive(tz: _Tokenizer, env):
    left = _parse_term(tz, env)
    while tz.peek()[1] in ("+", "-"):
        _, op = tz.next()
        right = _parse_term(tz, env)
        left = left + right if op == "+" else left - right
    return left


def _parse_expr(tz: _Tokenizer, env):
    left = _parse_additive(tz, env)
    kind, value = tz.peek()
    if value in _COMPARE_OPS:
        tz.next()
        right = _parse_additive(tz, env)
        return _COMPARE_OPS[value](left, right)
    return left


def evaluate(formula: str, raw_value) -> float:
    """Substitute ``{v}`` with raw_value and evaluate the formula."""
    if raw_value is None or raw_value == "":
        raise FormulaError("blank value")

    is_number = isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool)
    if not is_number:
        try:
            raw_value = float(raw_value)
            is_number = True
        except (TypeError, ValueError):
            pass

    literal = str(raw_value) if not is_number else repr(raw_value)
    text = formula.replace("{v}", literal if is_number else f'"{raw_value}"')

    tz = _Tokenizer(text.lstrip("="))
    result = _parse_expr(tz, {"v": raw_value})
    return float(result)
