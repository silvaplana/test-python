"""Execution de la formule Python ecrite par l'IA pour un previsionnel.

Le code vient d'un modele d'IA, qui lit des textes venus de l'exterieur
(libelles de la banque...) : il n'est jamais execute dans le serveur
lui-meme, et il est traite comme hostile. Trois protections independantes :
1. verification du code avant execution (check) : une fonction
   prevoir(donnees, p), pas d'import hors math et datetime, pas de nom ou
   d'attribut "_..." ni d'attribut d'introspection (gi_frame, f_back,
   f_globals... : acces aux entrailles de Python), pas de fonction integree
   dangereuse (open, eval, exec, getattr...) ;
2. execution dans un processus Python separe (run) : fonctions integrees
   limitees a une liste sure, imports limites a math et datetime, temps de
   calcul, memoire et ecriture de fichiers bornes, aucun nouveau processus,
   et delai maximum ;
3. dans ce processus, un "audit hook" de Python (impossible a retirer)
   refuse toute operation sensible pendant le calcul : ouverture de
   fichier, reseau, lancement de programme, import d'un autre module...
   Meme une formule qui contournerait 1 et 2 ne peut donc ni lire les
   donnees du serveur ni communiquer.
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
# Attributs d'introspection : depuis un generateur ou une trace d'erreur, ils
# remontent aux variables du programme qui lance la formule (donc a sys, os,
# open...). Prefixes des cadres d'execution (f_), generateurs (gi_),
# coroutines (cr_, ag_), traces (tb_) et objets code (co_).
FORBIDDEN_ATTRIBUTE_PREFIXES = ("gi_", "cr_", "ag_", "f_", "tb_", "co_")
# format / format_map : "{0.attribut}".format(x) lit un attribut par son nom
# sans passer par la verification ; mro : remonte a la classe object.
FORBIDDEN_ATTRIBUTES = {"format", "format_map", "mro", "func_globals", "func_code", "sys", "modules"}

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
    # Aucun nouveau processus (os.system, subprocess...).
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
except Exception:
    pass
import math, datetime
# strptime importe _strptime a chaque appel : charge ici, avant
# l'interdiction des imports, et autorise ci-dessous (la verification du
# code refuse de toute facon un "import _strptime" ecrit dans la formule).
import _strptime
datetime.datetime.strptime("2026-01-01", "%%Y-%%m-%%d")
request = json.loads(sys.stdin.read())
MODULES = {"math": math, "datetime": datetime, "_strptime": _strptime}
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
# Pendant le calcul, toute operation sensible signalee par Python (fichier,
# reseau, programme, import...) est refusee, sauf : la compilation et
# l'execution du code de la formule (une fois chacune) et l'import de math
# et datetime. Un audit hook ne peut pas etre retire.
state = {"compile": 1, "exec": 1, "done": False}
def audit(event, args):
    if state["done"]:
        return
    if event == "import" and args and args[0] in MODULES:
        return
    if state.get(event, 0) > 0:
        state[event] -= 1
        return
    raise RuntimeError("Opération interdite dans la formule : " + event)
sys.addaudithook(audit)
try:
    exec(compile(request["code"], "formule", "exec"), scope)
    points = scope["prevoir"](request["donnees"], request["params"])
    out = {"ok": True, "points": points}
except BaseException as exc:
    out = {"ok": False, "error": type(exc).__name__ + " : " + str(exc)[:300]}
try:
    answer = json.dumps(out, default=str)
except BaseException as exc:
    answer = json.dumps({"ok": False, "error": "Résultat de la formule illisible"})
state["done"] = True
sys.stdout.write(answer)
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
        elif isinstance(node, ast.Attribute) and (
            node.attr.startswith("_")
            or node.attr.startswith(FORBIDDEN_ATTRIBUTE_PREFIXES)
            or node.attr in FORBIDDEN_ATTRIBUTES
        ):
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
