"""Safe condition evaluation engine for Forge V2.

Provides AST-based boolean expression evaluation for workflow and task
conditional execution ('when' clauses) without third-party dependencies
and with strict security guarantees (no code execution or arbitrary function calls).
"""

from __future__ import annotations

import ast
import os
import re
from typing import Any, Callable

from forge.core.task import ExecutionContext


class ConditionEvaluationError(Exception):
    """Raised when a condition expression cannot be safely evaluated."""
    pass


class ConditionSyntaxError(Exception):
    """Raised when a condition expression is malformed."""
    pass


def _strip_template_braces(expr: str) -> str:
    """Strip optional wrapping {{ ... }} delimiters from an expression."""
    s = expr.strip()
    if s.startswith("{{") and s.endswith("}}"):
        s = s[2:-2].strip()
    return s


def _safe_str(val: Any) -> str:
    """Format value concisely for diagnostics."""
    if isinstance(val, str):
        return f"'{val}'"
    return str(val)


class _SafeASTEvaluator:
    """Evaluates an AST expression tree against runtime context."""

    def __init__(self, context: ExecutionContext) -> None:
        self.context = context
        self.parameters = context.parameters or {}
        self.outputs = context.outputs or {}
        self.resolved_symbols: dict[str, Any] = {}

    def evaluate(self, node: ast.AST) -> Any:
        method = getattr(self, f"_eval_{type(node).__name__}", None)
        if method is None:
            raise ConditionEvaluationError(
                f"Disallowed expression element '{type(node).__name__}'. "
                f"Only comparisons, logical operators, literals, and context references are permitted."
            )
        return method(node)

    def _eval_Expression(self, node: ast.Expression) -> Any:
        return self.evaluate(node.body)

    def _eval_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def _eval_Name(self, node: ast.Name) -> Any:
        name = node.id
        lower = name.lower()

        # Built-in literals
        if lower == "true":
            return True
        if lower == "false":
            return False
        if lower in ("none", "null"):
            return None

        # Top-level context namespaces
        if name == "parameters":
            return self.parameters
        if name == "outputs":
            return self.outputs
        if name == "env":
            return dict(os.environ)

        # Check parameter lookup
        if name in self.parameters:
            val = self.parameters[name]
            self.resolved_symbols[name] = val
            return val

        # Check environment variable lookup
        if name in os.environ:
            val = os.environ[name]
            self.resolved_symbols[f"env.{name}"] = val
            return val

        # Unknown name evaluates to None
        self.resolved_symbols[name] = None
        return None

    def _eval_Attribute(self, node: ast.Attribute) -> Any:
        val = self.evaluate(node.value)
        attr = node.attr

        if val is None:
            return None

        if isinstance(val, dict):
            res = val.get(attr)
            return res

        # For object instances with attributes or to_dict
        if hasattr(val, attr):
            return getattr(val, attr)

        if hasattr(val, "to_dict") and callable(val.to_dict):
            d = val.to_dict()
            if isinstance(d, dict):
                return d.get(attr)

        return None

    def _eval_Subscript(self, node: ast.Subscript) -> Any:
        val = self.evaluate(node.value)
        slice_val = self.evaluate(node.slice)

        if val is None:
            return None

        try:
            return val[slice_val]
        except (KeyError, IndexError, TypeError):
            return None

    def _eval_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.evaluate(node.operand)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise ConditionEvaluationError(f"Unsupported unary operator: {type(node.op).__name__}")

    def _eval_BinOp(self, node: ast.BinOp) -> Any:
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        op = node.op

        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        raise ConditionEvaluationError(f"Unsupported binary operator: {type(op).__name__}")

    def _eval_BoolOp(self, node: ast.BoolOp) -> bool:
        if isinstance(node.op, ast.And):
            for v in node.values:
                if not bool(self.evaluate(v)):
                    return False
            return True

        if isinstance(node.op, ast.Or):
            for v in node.values:
                if bool(self.evaluate(v)):
                    return True
            return False

        raise ConditionEvaluationError(f"Unsupported boolean operator: {type(node.op).__name__}")

    def _eval_Compare(self, node: ast.Compare) -> bool:
        left = self.evaluate(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.evaluate(comparator)
            if not self._compare_single(left, op, right):
                return False
            left = right
        return True

    def _compare_single(self, left: Any, op: ast.cmpop, right: Any) -> bool:
        # Type coercion for boolean string representations
        if isinstance(left, bool) and isinstance(right, str):
            if right.lower() in ("true", "false"):
                right = right.lower() == "true"
        elif isinstance(right, bool) and isinstance(left, str):
            if left.lower() in ("true", "false"):
                left = left.lower() == "true"

        # Coerce numeric comparisons when comparing numeric strings to numbers
        if isinstance(left, (int, float)) and isinstance(right, str):
            try:
                right = float(right) if "." in right else int(right)
            except ValueError:
                pass
        elif isinstance(right, (int, float)) and isinstance(left, str):
            try:
                left = float(left) if "." in left else int(left)
            except ValueError:
                pass

        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Lt):
            try:
                return left < right
            except TypeError:
                return False
        if isinstance(op, ast.LtE):
            try:
                return left <= right
            except TypeError:
                return False
        if isinstance(op, ast.Gt):
            try:
                return left > right
            except TypeError:
                return False
        if isinstance(op, ast.GtE):
            try:
                return left >= right
            except TypeError:
                return False
        if isinstance(op, ast.In):
            try:
                return left in right
            except TypeError:
                return False
        if isinstance(op, ast.NotIn):
            try:
                return left not in right
            except TypeError:
                return False
        if isinstance(op, ast.Is):
            return left is right
        if isinstance(op, ast.IsNot):
            return left is not right

        raise ConditionEvaluationError(f"Unsupported comparison operator: {type(op).__name__}")

    def _eval_List(self, node: ast.List) -> list[Any]:
        return [self.evaluate(elt) for elt in node.elts]

    def _eval_Tuple(self, node: ast.Tuple) -> tuple[Any, ...]:
        return tuple(self.evaluate(elt) for elt in node.elts)

    def _eval_Dict(self, node: ast.Dict) -> dict[Any, Any]:
        return {self.evaluate(k): self.evaluate(v) for k, v in zip(node.keys, node.values)}


def validate_condition_syntax(condition: str) -> None:
    """Validate that a condition string is syntactically sound and safe.

    Raises:
        ConditionSyntaxError: If the expression has invalid Python syntax.
        ConditionEvaluationError: If the expression contains disallowed AST constructs.
    """
    if not condition or not condition.strip():
        return

    clean_expr = _strip_template_braces(condition)
    try:
        tree = ast.parse(clean_expr, mode="eval")
    except SyntaxError as e:
        raise ConditionSyntaxError(f"Invalid condition syntax '{condition}': {e}") from e

    # Check for forbidden nodes (e.g. Call, Lambda, Comprehension, Import)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call, ast.Lambda, ast.comprehension, ast.Yield, ast.YieldFrom)):
            raise ConditionEvaluationError(
                f"Disallowed construct '{type(node).__name__}' in condition '{condition}'. Function calls are not permitted."
            )


def evaluate_condition(
    condition: str | bool | Callable[[ExecutionContext], bool] | None,
    context: ExecutionContext,
) -> tuple[bool, str]:
    """Evaluate a condition expression against an execution context.

    Returns:
        (is_met, reason): A tuple where is_met is True if the condition allows execution,
        and reason is a human-readable explanation if skipped or satisfied.
    """
    # 1. Unconditional
    if condition is None:
        return True, ""

    # 2. Literal boolean
    if isinstance(condition, bool):
        if condition:
            return True, ""
        return False, "Condition literal is False"

    # 3. Callable custom condition
    if callable(condition):
        try:
            result = bool(condition(context))
            if result:
                return True, ""
            return False, f"Custom condition callable returned False"
        except Exception as exc:
            return False, f"Condition callable raised error: {exc}"

    # 4. String expression
    if not isinstance(condition, str):
        return True, ""

    expr_str = condition.strip()
    if not expr_str:
        return True, ""

    clean_expr = _strip_template_braces(expr_str)

    # Fast-path for simple literals
    if clean_expr.lower() in ("true", "1"):
        return True, ""
    if clean_expr.lower() in ("false", "0"):
        return False, f"Condition '{expr_str}' evaluated to False"

    try:
        tree = ast.parse(clean_expr, mode="eval")
    except SyntaxError as err:
        raise ConditionSyntaxError(f"Syntax error parsing condition '{expr_str}': {err}") from err

    evaluator = _SafeASTEvaluator(context)
    try:
        result = evaluator.evaluate(tree)
        is_met = bool(result)
        if is_met:
            return True, ""

        # Build diagnostic detail of symbols involved
        symbols_desc = ""
        if evaluator.resolved_symbols:
            items = [f"{k}={_safe_str(v)}" for k, v in evaluator.resolved_symbols.items()]
            symbols_desc = f" ({', '.join(items)})"

        reason = f"Condition '{expr_str}' evaluated to False{symbols_desc}"
        return False, reason

    except Exception as exc:
        raise ConditionEvaluationError(
            f"Failed to evaluate condition '{expr_str}': {exc}"
        ) from exc
