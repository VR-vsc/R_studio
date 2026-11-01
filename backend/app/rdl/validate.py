"""Проверка RDL-документа: структура (pydantic) + смысл (имена, выражения, Ujin-мины)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from .expr import RESERVED, ExprError, compile_expr
from .models import CATEGORIES, DeviceSpec

Issue = Dict[str, str]

_PYDANTIC_RU = {
    "missing": "обязательное поле",
    "string_pattern_mismatch": "только строчная латиница, цифры и _, начинается с буквы, без дефисов",
    "extra_forbidden": "лишнее поле",
    "literal_error": "недопустимое значение",
    "too_short": "слишком мало элементов",
    "string_too_short": "пустое значение",
    "string_too_long": "слишком длинно",
    "greater_than_equal": "слишком маленькое число",
    "greater_than": "должно быть больше нуля",
    "less_than_equal": "слишком большое число",
}


def _path(loc) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += ("." if out else "") + str(part)
    return out


def _issue(path: str, message: str, severity: str = "error") -> Issue:
    return {"path": path, "message": message, "severity": severity}


def analyze(raw: Any) -> Tuple[Optional[DeviceSpec], List[Issue]]:
    """Вернуть (spec или None, список замечаний). spec=None, если есть ошибки."""
    issues: List[Issue] = []
    try:
        spec = DeviceSpec.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            loc = [p for p in err["loc"] if not (isinstance(p, str) and p in
                                                  ("bool", "int", "float", "str"))]
            msg = _PYDANTIC_RU.get(err["type"], err["msg"])
            issues.append(_issue(_path(loc), msg))
        return None, _dedupe(issues)

    issues.extend(_semantic(spec))
    has_errors = any(i["severity"] == "error" for i in issues)
    return (None if has_errors else spec), issues


def _dedupe(issues: List[Issue]) -> List[Issue]:
    seen, out = set(), []
    for i in issues:
        key = (i["path"], i["message"])
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def _semantic(spec: DeviceSpec) -> List[Issue]:
    issues: List[Issue] = []
    names: Dict[str, str] = {}

    if spec.category not in CATEGORIES:
        issues.append(_issue("category", "неизвестная категория: " + ", ".join(CATEGORIES),
                             "warning"))

    # --- сигналы
    for i, s in enumerate(spec.signals):
        p = f"signals[{i}]"
        if s.name in RESERVED:
            issues.append(_issue(f"{p}.name", f"имя '{s.name}' зарезервировано"))
        if s.name in names:
            issues.append(_issue(f"{p}.name", f"имя '{s.name}' уже занято"))
        names[s.name] = "signal"
        acc = s.effective_access
        if s.group == "property" and acc != "r":
            issues.append(_issue(f"{p}.access", "свойство только читается (r); "
                                 "управляемый сигнал — это «возможность»"))
        if s.group == "capability" and acc == "r":
            issues.append(_issue(f"{p}.access", "возможность должна быть управляемой (rw или w)"))
        if s.group == "environment" and acc != "w":
            issues.append(_issue(f"{p}.access", "окружение задаётся только эмулятором (w)"))
        if s.min is not None and s.max is not None and s.min > s.max:
            issues.append(_issue(f"{p}.min", "минимум больше максимума"))
        if s.type in ("number", "bool", "enum", "button"):
            if isinstance(s.default, str):
                issues.append(_issue(f"{p}.default", "значение по умолчанию должно быть числом"))
            else:
                d = float(s.default)
                if s.min is not None and d < s.min or s.max is not None and d > s.max:
                    issues.append(_issue(f"{p}.default", "значение по умолчанию вне диапазона"))
        if s.type == "enum":
            if not s.options:
                issues.append(_issue(f"{p}.options", "у перечисления нужны варианты"))
            for k in s.options:
                try:
                    int(k)
                except ValueError:
                    issues.append(_issue(f"{p}.options", f"ключ варианта '{k}' должен быть целым"))
        if s.type == "button" and s.group not in ("capability",):
            issues.append(_issue(f"{p}.group", "кнопка — это возможность"))
        if s.monotonic and s.type != "number":
            issues.append(_issue(f"{p}.monotonic", "монотонным бывает только число"))
        if (s.group in ("property", "capability", "setting") and s.type != "text"
                and not isinstance(s.default, str) and float(s.default) == 0):
            issues.append(_issue(f"{p}.default", "0 на платформу уходит как 0.001 "
                                 "(мина Ujin №1) — это сделает рантайм сам", "info"))

    for k in spec.vars:
        p = f"vars.{k}"
        if not _ident(k):
            issues.append(_issue(p, "имя переменной: строчная латиница, цифры, _"))
        if k in RESERVED or k in names:
            issues.append(_issue(p, f"имя '{k}' уже занято"))
        names.setdefault(k, "var")

    known = set(names)
    signals = {s.name: s for s in spec.signals}

    # --- поведение
    rule_ids = set()
    for i, r in enumerate(spec.behavior):
        p = f"behavior[{i}]"
        if r.id:
            if r.id in rule_ids:
                issues.append(_issue(f"{p}.id", f"правило '{r.id}' повторяется"))
            rule_ids.add(r.id)
        if ":" in r.on:
            kind, target = r.on.split(":", 1)
            sig = signals.get(target)
            if sig is None:
                issues.append(_issue(f"{p}.on", f"нет сигнала '{target}'"))
            elif kind == "command" and sig.effective_access == "r":
                issues.append(_issue(f"{p}.on", f"'{target}' только читается — команд не будет"))
        if r.when not in (None, ""):
            _expr(issues, f"{p}.when", r.when, known)
        for j, a in enumerate(r.do):
            ap = f"{p}.do[{j}]"
            if (a.set is None) == (a.log is None):
                issues.append(_issue(ap, "действие: укажите либо set (+to), либо log"))
                continue
            if a.set is not None:
                if a.set not in known:
                    issues.append(_issue(f"{ap}.set", f"нет сигнала или переменной '{a.set}'"))
                if a.to is None:
                    issues.append(_issue(f"{ap}.to", "укажите значение (to)"))
                else:
                    _expr(issues, f"{ap}.to", a.to, known)
                if a.then is not None:
                    _expr(issues, f"{ap}.then", a.then, known)
                if a.then is not None and a.hold is None:
                    issues.append(_issue(f"{ap}.then", "then работает только вместе с hold",
                                         "warning"))

    # --- события
    ev_names = set()
    for i, e in enumerate(spec.events):
        p = f"events[{i}]"
        if e.name in ev_names:
            issues.append(_issue(f"{p}.name", f"событие '{e.name}' повторяется"))
        ev_names.add(e.name)
        _expr(issues, f"{p}.when", e.when, known)
        for j, st in enumerate(e.stimulus):
            sig = signals.get(st.signal)
            if sig is None:
                issues.append(_issue(f"{p}.stimulus[{j}].signal", f"нет сигнала '{st.signal}'"))
            elif sig.effective_access == "r":
                issues.append(_issue(f"{p}.stimulus[{j}].signal",
                                     "стимул задаётся через окружение или возможность, а не показание"))

    # --- полнота (для людей)
    groups = {s.group for s in spec.signals}
    if "property" not in groups:
        issues.append(_issue("signals", "нет ни одного свойства — устройству нечего показывать",
                             "warning"))
    for s in spec.signals:
        if s.group == "capability" and not _reacts(spec, s.name):
            issues.append(_issue("behavior", f"возможность '{s.name}' ни на что не влияет — "
                                 "добавьте правило или используйте её в выражении", "warning"))
    return issues


def _reacts(spec: DeviceSpec, name: str) -> bool:
    for r in spec.behavior:
        if r.on in (f"command:{name}", f"change:{name}", "command"):
            return True
        exprs = [r.when] + [a.to for a in r.do] + [a.then for a in r.do]
        for e in exprs:
            if isinstance(e, str) and name in _words(e):
                return True
    return any(name in _words(e.when) for e in spec.events)


def _words(src: str):
    import re
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", src))


def _ident(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"[a-z][a-z0-9_]{0,31}", s))


def _expr(issues: List[Issue], path: str, src, known) -> None:
    try:
        compile_expr(src, known)
    except ExprError as exc:
        issues.append(_issue(path, str(exc)))
