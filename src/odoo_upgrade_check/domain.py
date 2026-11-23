"""Turn the domains of Odoo 16 `attrs` / `states` into Odoo 17 expressions.

    attrs="{'invisible': [('state', '!=', 'draft')]}"  ->  invisible="state != 'draft'"
"""

import ast

OPERATORS = {"=": "==", "==": "==", "!=": "!=", "<>": "!=", "<": "<", ">": ">",
             "<=": "<=", ">=": ">=", "in": "in", "not in": "not in"}

# Precedence: the higher binds tighter. Comparisons and "not" bind tighter than and/or.
OR, AND, NOT, ATOM = 1, 2, 3, 4


class Unsupported(ValueError):
    """The domain uses something without a plain Python equivalent (ilike, child_of...)."""


def attrs_to_attributes(text):
    """{'invisible': domain, ...} -> {'invisible': 'expression', ...}

    Raises Unsupported (or SyntaxError) when the attrs cannot be converted.
    """
    node = ast.parse(text.strip(), mode="eval").body
    if not isinstance(node, ast.Dict):
        raise Unsupported("attrs is not a dictionary")
    result = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise Unsupported("attrs key is not a string")
        result[key.value] = domain_to_expression(value)
    return result


def states_to_invisible(states):
    """states="draft,sent" -> invisible="state not in ('draft', 'sent')" """
    values = [state.strip() for state in states.split(",") if state.strip()]
    if len(values) == 1:
        return f"state != {values[0]!r}"
    return f"state not in {tuple(values)!r}"


def domain_to_expression(node):
    if isinstance(node, str):
        node = ast.parse(node.strip(), mode="eval").body
    if not isinstance(node, (ast.List, ast.Tuple)):
        # A bare True/1 (e.g. {'invisible': True}) is already an expression.
        if isinstance(node, ast.Constant):
            return "1" if node.value else "0"
        raise Unsupported("domain is not a list")
    terms = list(node.elts)
    if not terms:
        return "1"  # an empty domain is always true
    expressions = []
    while terms:
        expression, _precedence = _term(terms)
        expressions.append(expression)
    if len(expressions) == 1:
        return expressions[0][0]
    return " and ".join(_wrap(expression, AND) for expression in expressions)


def _wrap(expression, precedence):
    text, own = expression
    return f"({text})" if own < precedence else text


def _term(terms):
    """Consume one prefix-notation term; return ((text, precedence), precedence)."""
    node = terms.pop(0)
    if isinstance(node, ast.Constant) and node.value in ("&", "|"):
        left, _ = _term(terms)
        right, _ = _term(terms)
        precedence = AND if node.value == "&" else OR
        joiner = " and " if node.value == "&" else " or "
        result = (_wrap(left, precedence) + joiner + _wrap(right, precedence), precedence)
        return result, precedence
    if isinstance(node, ast.Constant) and node.value == "!":
        inner, _ = _term(terms)
        result = ("not " + _wrap(inner, NOT + 1), NOT)
        return result, NOT
    if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) == 3:
        return _leaf(*node.elts), ATOM
    raise Unsupported("unexpected element in domain")


def _leaf(field, operator, value):
    if not (isinstance(field, ast.Constant) and isinstance(field.value, str)):
        raise Unsupported("field name is not a string")
    if not (isinstance(operator, ast.Constant) and operator.value in OPERATORS):
        raise Unsupported(f"operator {ast.unparse(operator)} has no Python equivalent")
    name, op = field.value, OPERATORS[operator.value]
    if isinstance(value, ast.Constant) and op in ("==", "!=") and any(value.value is v for v in (False, True, None)):
        truthy = bool(value.value) == (op == "==")
        return (name if truthy else f"not {name}", NOT if not truthy else ATOM)
    return (f"{name} {op} {ast.unparse(value)}", ATOM)
