"""A restricted arithmetic-expression evaluator for user-authored derived
variables (e.g. "temp_u_p + temp_u_i + temp_u_d", "sqrt(abs(error))").

Deliberately not Python's eval()/exec(): those run arbitrary code (file
access, imports, anything) for a feature whose whole point is letting an
end user type a formula into a text field. This walks the parsed AST and
only accepts a small whitelist of node types and function names -- anything
else (attribute access, subscripting, comprehensions, lambdas, calls to
anything not on the whitelist, ...) raises SafeEvalError rather than
silently doing something unexpected.
"""

import ast
import operator

import numpy as np

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS = {
    "abs": np.abs,
    "min": np.minimum,
    "max": np.maximum,
    "sqrt": np.sqrt,
    "log": np.log,
    "log10": np.log10,
    "exp": np.exp,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "clip": np.clip,
}


class SafeEvalError(ValueError):
    pass


def _eval_node(node, variables):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise SafeEvalError(f"Unsupported constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise SafeEvalError(
                f"Unknown variable '{node.id}' -- must be one of: "
                f"{', '.join(sorted(variables)) or '(none available)'}"
            )
        return variables[node.id]
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise SafeEvalError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_eval_node(node.left, variables), _eval_node(node.right, variables))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise SafeEvalError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op(_eval_node(node.operand, variables))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            allowed = ", ".join(sorted(_FUNCTIONS))
            raise SafeEvalError(f"Unsupported function call -- allowed: {allowed}")
        if node.keywords:
            raise SafeEvalError("Keyword arguments are not supported")
        args = [_eval_node(a, variables) for a in node.args]
        return _FUNCTIONS[node.func.id](*args)
    raise SafeEvalError(f"Unsupported expression element: {type(node).__name__}")


def evaluate(expression, variables):
    """variables: dict[str, np.ndarray | float] of names the expression may
    reference. Returns whatever the expression evaluates to (typically an
    ndarray, if any variable used was one). Raises SafeEvalError for
    anything outside the supported grammar, and ValueError/ZeroDivisionError
    /etc. for legitimate runtime numeric errors (e.g. division by zero) --
    callers should catch both."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SafeEvalError(f"Invalid expression syntax: {exc}") from exc
    return _eval_node(tree, variables)


def referenced_names(expression):
    """Every ast.Name the expression references as a *variable*, valid or
    not -- used to check "does this run actually have the channels this
    formula needs" before attempting to evaluate it. Excludes function
    names in call position (e.g. the `sqrt` in `sqrt(x)`): ast.Call.func is
    itself an ast.Name node, so a naive ast.walk() would otherwise treat
    every function call in the expression as an extra required channel."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SafeEvalError(f"Invalid expression syntax: {exc}") from exc
    call_func_ids = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id not in call_func_ids
    }
