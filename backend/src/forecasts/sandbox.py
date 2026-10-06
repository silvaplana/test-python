"""Execution de la formule Python ecrite par l'IA pour un previsionnel.

Le code vient d'un modele d'IA : il n'est jamais execute dans le serveur
lui-meme. Deux protections :
1. verification du code avant execution (check) : une fonction
   prevoir(donnees, p), pas d'import hors math et datetime, pas de nom ou
   d'attribut "_..." (acces aux entrailles de Python), pas de fonction
   integree dangereuse (open, eval, exec, getattr...) ;
2. execution dans un processus Python separe (run) : fonctions integrees
   limitees a une liste sure, imports limites a math et datetime, temps de
   calcul, memoire et ecriture de fichiers bornes, et delai maximum.
"""

from __future__ import annotations

import ast
import json
import math
import subprocess
import sys

ALLOWED_MODULES = {"math", "datetime"}
FORBIDDEN_NAMES = {
    "open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "input", "breakpoint", "memoryview", "type", "object", "super", "help", "exit", "quit",
    "classmethod", "staticmethod", "property",
}
# Delai maximum d'une execution (secondes) et memoire maximum (octets).
TIMEOUT = 10
MEMORY = 512 * 1024 * 1024

# Programme lance dans le processus separe : lit {code, donnees, params} sur
# l'entree standard, ecrit {"ok", "points"} ou {"ok": false, "error"}.
_RUNNER = r'''
import json, sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (%(memory)d, %(memory)d))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
except Exception:
    pass
import math, datetime
request = json.loads(sys.stdin.read())
MODULES = {"math": math, "datetime": datetime}
def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name not in MODULES:
        raise ImportError("Import interdit : " + name)
    return MODULES[name]
SAFE = ["abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "int", "isinstance",
        "len", "list", "map", "max", "min", "pow", "range", "reversed", "round", "set", "sorted", "str", "sum",
        "tuple", "zip", "ValueError", "KeyError", "IndexError", "TypeError", "ZeroDivisionError", "Exception",
        "True", "False", "None"]
import builtins
safe_builtins = {name: getattr(builtins, name) for name in SAFE}
safe_builtins["__import__"] = safe_import
scope = {"__builtins__": safe_builtins, "__name__": "formule"}
try:
    exec(compile(request["code"], "formule", "exec"), scope)
    points = scope["prevoir"](request["donnees"], request["params"])
    out = {"ok": True, "points": points}
except BaseException as exc:
    out = {"ok": False, "error": type(exc).__name__ + " : " + str(exc)[:300]}
sys.stdout.write(json.dumps(out, default=str))
''' % {"memory": MEMORY}


class FormulaError(ValueError):
    """Formule refusee ou en echec (message affichable tel quel)."""


def check(code: str) -> None:
    """Verifie le code avant toute execution ; FormulaError si refuse."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise FormulaError(f"Formule illisible (ligne {exc.lineno}) : {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_MODULES:
                    raise FormulaError(f"Import interdit : {alias.name} (seuls math et datetime)")
        elif isinstance(node, ast.ImportFrom):
            if node.module not in ALLOWED_MODULES or node.level:
                raise FormulaError(f"Import interdit : {node.module} (seuls math et datetime)")
        elif isinstance(node, ast.Name) and (node.id.startswith("_") or node.id in FORBIDDEN_NAMES):
            raise FormulaError(f"Nom interdit dans la formule : {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise FormulaError(f"Attribut interdit dans la formule : {node.attr}")
        elif isinstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await, ast.ClassDef)):
            raise FormulaError("Construction interdite dans la formule (global, classe, async)")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "prevoir" for n in tree.body):
        raise FormulaError("La formule doit définir une fonction prevoir(donnees, p)")


def run(code: str, donnees: dict, params: dict) -> list[float]:
    """Execute prevoir(donnees, params) dans un processus separe et retourne
    le solde prevu a chaque semaine de donnees["semaines"] (euros)."""
    check(code)
    request = json.dumps({"code": code, "donnees": donnees, "params": params}, ensure_ascii=False)
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _RUNNER],
            input=request,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env={},
        )
    except subprocess.TimeoutExpired as exc:
        raise FormulaError(f"La formule a dépassé {TIMEOUT} s de calcul") from exc
    try:
        out = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FormulaError("La formule a été arrêtée (trop de calcul ou de mémoire)") from exc
    if not out.get("ok"):
        raise FormulaError(f"La formule a échoué : {out.get('error')}")
    return _balances(out["points"], len(donnees["semaines"]))


def _balances(points, expected: int) -> list[float]:
    """Accepte une liste de nombres ou de {"solde": ...} ; une valeur par
    semaine."""
    if not isinstance(points, list) or len(points) != expected:
        size = len(points) if isinstance(points, list) else "?"
        raise FormulaError(f"La formule doit renvoyer une valeur par semaine ({expected}), elle en renvoie {size}")
    balances = []
    for point in points:
        value = point.get("solde") if isinstance(point, dict) else point
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise FormulaError(f"Solde invalide dans le résultat de la formule : {value!r}")
        balances.append(round(float(value), 2))
    return balances
