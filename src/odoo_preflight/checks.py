"""The rules. Each one was checked against the source code of the Odoo version it names.

Rules marked "data" use what tools/build_data.py found missing in the newer version
(addons, asset bundles, JS modules, views, templates, models, fields).
"""

import ast
import functools
import json
import re
from pathlib import Path

from .core import rule
from .domain import Unsupported, attrs_to_attributes, states_to_invisible

DATA = Path(__file__).parent / "data"

# Renames worth suggesting when a model disappears.
MODEL_RENAMES = {
    "mail.channel": "discuss.channel",
    "mail.channel.member": "discuss.channel.member",
    "mail.channel.rtc.session": "discuss.channel.rtc.session",
}
BUNDLE_RENAMES = {"point_of_sale.assets": "point_of_sale._assets_pos"}


@functools.lru_cache(maxsize=None)
def removed(version):
    """What existed in version - 1 and is gone in `version`."""
    data = json.loads((DATA / f"upgrade-{version}.json").read_text(encoding="utf-8"))
    for key in ("addons", "bundles", "legacy_modules", "views", "templates", "models"):
        data[key] = set(data[key])
    data["fields"] = {model: set(fields) for model, fields in data["fields"].items()}
    return data


def line_of(text, needle):
    """1-based line and column of the first occurrence of needle in text."""
    index = text.find(needle)
    if index < 0:
        return 1, 1
    return text.count("\n", 0, index) + 1, index - text.rfind("\n", 0, index)


# --- manifest ----------------------------------------------------------------

@rule("manifest-version", 0, "warning", "manifest", "The version in the manifest must start with the target series")
def manifest_version(module, target):
    version = str(module.manifest.get("version", ""))
    if module.series and module.series != target:
        text = (module.path / "__manifest__.py").read_text(encoding="utf-8")
        new = re.sub(r"^\d+\.0", f"{target}.0", version)
        yield (*line_of(text, version), f"Version {version} is for Odoo {module.series}.", f'"version": "{new}"')


def _removed_dependencies(version):
    def check(module, target):
        text = (module.path / "__manifest__.py").read_text(encoding="utf-8")
        for depend in module.manifest.get("depends", []):
            if depend in removed(version)["addons"]:
                yield (*line_of(text, f'"{depend}"' if f'"{depend}"' in text else f"'{depend}'"),
                       f"Odoo {version} has no '{depend}' module (removed or merged into another one).", "")
        for bundle in module.manifest.get("assets", {}):
            if bundle in removed(version)["bundles"]:
                fix = f'"{BUNDLE_RENAMES[bundle]}"' if bundle in BUNDLE_RENAMES else ""
                yield (*line_of(text, bundle), f"Odoo {version} has no asset bundle '{bundle}'.", fix)
    return check


for _version in (17, 18):
    rule("removed-dependency", _version, "error", "manifest",
         "Depends on a module or asset bundle that no longer exists (data)")(_removed_dependencies(_version))


# --- Python --------------------------------------------------------------------

def classes(tree):
    return [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def methods(tree, name):
    for cls in classes(tree):
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                yield node


def calls(tree, name):
    """Calls to x.name(...)"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name:
            yield node


def is_field_call(node):
    """fields.Char(...), fields.Many2one(...)"""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "fields")


def field_calls(tree):
    return (node for node in ast.walk(tree) if is_field_call(node))


@rule("name-get", 17, "error", "python", "Overriding name_get() no longer changes the display name")
def name_get(tree):
    for node in methods(tree, "name_get"):
        yield (node.lineno, node.col_offset + 1,
               "Since Odoo 17 the display name does not come from name_get(): this override is ignored.",
               "@api.depends(...)\ndef _compute_display_name(self):\n    for record in self:\n        record.display_name = ...")


@rule("name-get-call", 17, "warning", "python", "name_get() is deprecated")
def name_get_call(tree):
    for node in calls(tree, "name_get"):
        yield node.lineno, node.col_offset + 1, "name_get() is deprecated since Odoo 17 and removed in 18.", "record.display_name"


@rule("name-search-signature", 17, "error", "python", "_name_search() has a new signature")
def name_search_signature(tree):
    for node in methods(tree, "_name_search"):
        names = [arg.arg for arg in node.args.args]
        if "name_get_uid" in names or "args" in names:
            yield (node.lineno, node.col_offset + 1,
                   "Since Odoo 17, _name_search() takes a domain instead of args and no name_get_uid.",
                   "def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):")


@rule("field-states", 17, "error", "python", "The states= parameter of fields is ignored")
def field_states(tree):
    for node in field_calls(tree):
        for keyword in node.keywords:
            if keyword.arg == "states":
                yield (keyword.value.lineno, keyword.value.col_offset + 1,
                       "Since Odoo 17 fields ignore states=: the field is no longer readonly/required by state.",
                       "Set readonly=\"state != 'draft'\" (or required=...) on the field in the views.")


@rule("read-group-signature", 17, "error", "python", "_read_group() has a new signature")
def read_group_signature(tree):
    old_keywords = {"fields", "lazy", "orderby"}
    for node in calls(tree, "_read_group"):
        used = old_keywords & {keyword.arg for keyword in node.keywords}
        if used:
            yield (node.lineno, node.col_offset + 1,
                   f"Since Odoo 17, _read_group() takes (domain, groupby, aggregates) and returns tuples; "
                   f"{', '.join(sorted(used))} no longer exist.",
                   "Use read_group() for the old behaviour, or _read_group(domain, ['partner_id'], ['amount:sum']).")
    for node in methods(tree, "_read_group"):
        names = [arg.arg for arg in node.args.args]
        if "fields" in names or "lazy" in names:
            yield (node.lineno, node.col_offset + 1, "Since Odoo 17, _read_group() has a new signature.",
                   "def _read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):")


@rule("name-search-removed", 18, "error", "python", "_name_search() was replaced by _search_display_name()")
def name_search_removed(tree):
    for node in methods(tree, "_name_search"):
        yield (node.lineno, node.col_offset + 1,
               "Odoo 18 no longer calls _name_search(): this override is ignored.",
               "@api.model\ndef _search_display_name(self, operator, value):\n    return domain")


@rule("name-get-removed", 18, "error", "python", "name_get() was removed")
def name_get_removed(tree):
    for node in calls(tree, "name_get"):
        yield node.lineno, node.col_offset + 1, "Odoo 18 has no name_get().", "record.display_name"


@rule("user-has-groups", 18, "error", "python", "user_has_groups() was removed")
def user_has_groups(tree):
    for node in calls(tree, "user_has_groups"):
        yield (node.lineno, node.col_offset + 1, "Odoo 18 has no user_has_groups().",
               "self.env.user.has_group('module.group'), or has_groups('a,!b') for several groups")


@rule("group-operator", 18, "warning", "python", "group_operator= was renamed aggregator=")
def group_operator(tree):
    for node in field_calls(tree):
        for keyword in node.keywords:
            if keyword.arg == "group_operator":
                yield keyword.value.lineno, keyword.value.col_offset + 1, "group_operator is deprecated since Odoo 18.", "aggregator=..."


ACCESS = {
    "check_access_rights": "check_access(operation) or has_access(operation)",
    "check_access_rule": "check_access(operation)",
    "_filter_access_rules": "_filtered_access(operation)",
    "_filter_access_rules_python": "_filtered_access(operation)",
}


@rule("access-methods", 18, "warning", "python", "check_access_rights() and check_access_rule() are deprecated")
def access_methods(tree):
    for name, replacement in ACCESS.items():
        for node in calls(tree, name):
            yield node.lineno, node.col_offset + 1, f"{name}() is deprecated since Odoo 18.", replacement


def _removed_models(version):
    def check(tree):
        gone = removed(version)["models"]
        own = {model_of_class(cls) for cls in classes(tree)}  # a module may recreate a removed model
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in gone and node.value not in own:
                rename = MODEL_RENAMES.get(node.value)
                yield (node.lineno, node.col_offset + 1, f"Odoo {version} has no model '{node.value}'.",
                       f"'{rename}'" if rename else "")
    return check


def model_of_class(cls):
    """The model a class defines or extends, when it says so plainly."""
    name = inherit = None
    for node in cls.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "_name" and isinstance(node.value, ast.Constant):
                name = node.value.value
            elif node.targets[0].id == "_inherit":
                if isinstance(node.value, ast.Constant):
                    inherit = node.value.value
                elif isinstance(node.value, ast.List) and len(node.value.elts) == 1 and isinstance(node.value.elts[0], ast.Constant):
                    inherit = node.value.elts[0].value
    return name or inherit


def own_fields(tree):
    """Fields this file declares, by model: they are not "removed"."""
    result = {}
    for cls in classes(tree):
        model = model_of_class(cls)
        for node in cls.body:
            if isinstance(node, ast.Assign) and is_field_call(node.value):
                result.setdefault(model, set()).update(t.id for t in node.targets if isinstance(t, ast.Name))
    return result


def _removed_fields_python(version):
    def check(tree):
        gone, declared = removed(version)["fields"], own_fields(tree)
        # 1. In a class of a known model: self.field, record.field, and field names in @api.depends.
        for cls in classes(tree):
            model = model_of_class(cls)
            fields = gone.get(model, set()) - declared.get(model, set())
            if not fields:
                continue
            for node in ast.walk(cls):
                if isinstance(node, ast.Attribute) and node.attr in fields and isinstance(node.value, ast.Name) and node.value.id == "self":
                    yield node.lineno, node.col_offset + 1, f"Odoo {version} has no field {model}.{node.attr}.", ""
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr in ("depends", "onchange", "constrains")):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.split(".")[0] in fields:
                            yield arg.lineno, arg.col_offset + 1, f"Odoo {version} has no field {model}.{arg.value.split('.')[0]}.", ""
        # 2. self.env['model'].search([('field', ...)]) / .create({'field': ...}) / .write(...)
        for node in ast.walk(tree):
            model = env_model(node)
            fields = gone.get(model, set()) - declared.get(model, set()) if model else set()
            if not fields:
                continue
            for name, located in field_names_in_call(node):
                if name in fields:
                    yield located.lineno, located.col_offset + 1, f"Odoo {version} has no field {model}.{name}.", ""
    return check


def env_model(node):
    """'stock.move.line' for env['stock.move.line'].search(...)"""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    target = node.func.value
    while isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute):
        target = target.func.value  # env['x'].sudo().search(...)
    if isinstance(target, ast.Subscript):
        key = target.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
    return None


def field_names_in_call(node):
    """Field names in domains ([('field', '=', x)]) and value dicts ({'field': x}) of a call."""
    for arg in list(node.args) + [keyword.value for keyword in node.keywords]:
        for item in ast.walk(arg):
            if isinstance(item, ast.Tuple) and len(item.elts) == 3 and isinstance(item.elts[0], ast.Constant):
                if isinstance(item.elts[0].value, str):
                    yield item.elts[0].value.split(".")[0], item.elts[0]
            elif isinstance(item, ast.Dict):
                for key in item.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        yield key.value, key


for _version in (17, 18):
    rule("removed-model", _version, "error", "python", "Uses a model that no longer exists (data)")(_removed_models(_version))
    rule("removed-field", _version, "error", "python", "Uses a field that no longer exists (data)")(_removed_fields_python(_version))


# --- XML -------------------------------------------------------------------------

def arch_nodes(root):
    return (node for node in root.iter() if node.in_view)


def _attribute_node(node, name):
    """<attribute name="attrs">...</attribute> in an inheriting view."""
    return node.tag == "attribute" and node.attrib.get("name") == name and node.in_view


@rule("view-attrs", 17, "error", "xml", "attrs and states are no longer supported in views")
def view_attrs(root):
    for node in arch_nodes(root):
        if "attrs" in node.attrib:
            attributes = _convert_attrs(node.attrib["attrs"], node.attrib.get("invisible"))
            fix = " ".join(f'{key}="{value}"' for key, value in attributes.items()) if attributes else ATTRS_HELP
            yield node.line, node.column, "Since Odoo 17 views reject attrs: the module cannot be installed.", fix
        if "states" in node.attrib:
            yield (node.line, node.column, "Since Odoo 17 views reject states: the module cannot be installed.",
                   f'invisible="{states_to_invisible(node.attrib["states"])}"')
        if _attribute_node(node, "attrs"):
            attributes = _convert_attrs(node.text)
            fix = "\n".join(f'<attribute name="{key}">{value}</attribute>' for key, value in attributes.items()) \
                if attributes else ATTRS_HELP
            yield node.line, node.column, "Since Odoo 17 views reject attrs: the module cannot be installed.", fix
        if _attribute_node(node, "states"):
            yield (node.line, node.column, "Since Odoo 17 views reject states: the module cannot be installed.",
                   f'<attribute name="invisible">{states_to_invisible(node.text)}</attribute>')


ATTRS_HELP = 'Write each condition as its own attribute: invisible="..." readonly="..." required="..."'


def _convert_attrs(text, invisible=None):
    """{'invisible': "state != 'draft'"}, or None when the domain has no plain Python equivalent."""
    try:
        attributes = attrs_to_attributes(text or "")
    except (Unsupported, SyntaxError, ValueError):
        return None
    if invisible in ("1", "True") and "invisible" in attributes:
        attributes["invisible"] = "1"  # already always invisible
    return attributes


@rule("list-view", 18, "error", "xml", "<tree> views are now <list>")
def list_view(root):
    for node in root.iter():
        if node.tag == "tree" and node.in_view:
            yield node.line, node.column, "Odoo 18 renamed the tree view to list.", "<list ...> ... </list>"
        elif node.tag == "xpath" and re.search(r"(^|/)tree\b", node.attrib.get("expr", "")):
            yield (node.line, node.column, "Odoo 18 renamed the tree view to list: this xpath finds nothing.",
                   re.sub(r"(^|/)tree\b", r"\1list", node.attrib["expr"]))
        elif node.tag == "field" and node.attrib.get("name") == "view_mode" and re.search(r"\btree\b", node.text):
            yield (node.line, node.column, "Odoo 18 renamed the tree view mode to list.",
                   re.sub(r"\btree\b", "list", node.text.strip()))


@rule("kanban-box", 18, "warning", "xml", "The kanban-box template is deprecated")
def kanban_box(root):
    for node in root.iter():
        if node.tag == "t" and node.attrib.get("t-name") == "kanban-box" and node.in_view:
            yield node.line, node.column, "Odoo 18 deprecates the kanban-box template.", '<t t-name="card">'


def _removed_xml(version):
    def check(root):
        data = removed(version)
        for node in root.iter():
            for attribute in ("inherit_id", "ref", "t-call"):
                value = node.attrib.get(attribute, "")
                if value in data["views"]:
                    yield node.line, node.column, f"Odoo {version} has no view '{value}'.", ""
            if node.attrib.get("t-inherit") in data["templates"]:
                yield node.line, node.column, f"Odoo {version} has no template '{node.attrib['t-inherit']}'.", ""
            if node.tag == "field" and node.attrib.get("name") == "model" and node.text.strip() in data["models"]:
                model = node.text.strip()
                rename = MODEL_RENAMES.get(model)
                yield node.line, node.column, f"Odoo {version} has no model '{model}'.", rename or ""
        yield from _removed_fields_xml(root, data, version)
    return check


def _removed_fields_xml(root, data, version):
    for record in root.iter():
        if record.tag != "record":
            continue
        fields = {child.attrib.get("name"): child for child in record.children if child.tag == "field"}
        # Data records: <record model="ir.cron"><field name="numbercall">
        model = record.attrib.get("model")
        for name, child in fields.items():
            if name in data["fields"].get(model, ()):
                yield child.line, child.column, f"Odoo {version} has no field {model}.{name}.", ""
        if model != "ir.ui.view" or "arch" not in fields:
            continue
        # Views: fields used in the architecture, or looked for by an inheriting view.
        view_model = fields["model"].text.strip() if "model" in fields else None
        if not view_model and "inherit_id" in fields:
            view_model = data["view_models"].get(fields["inherit_id"].attrib.get("ref", ""))
        gone = data["fields"].get(view_model, set())
        if not gone:
            continue
        for node in fields["arch"].iter():
            if node.tag == "field" and node.attrib.get("name") in gone and not _inside_subview(node, fields["arch"]):
                yield node.line, node.column, f"Odoo {version} has no field {view_model}.{node.attrib['name']}.", ""
            for name in re.findall(r"@name\s*=\s*['\"](\w+)['\"]", node.attrib.get("expr", "")):
                if name in gone and "field" in node.attrib.get("expr", ""):
                    yield (node.line, node.column,
                           f"Odoo {version} has no field {view_model}.{name}: this xpath finds nothing.", "")
                    break


def _inside_subview(node, arch):
    """Fields of an embedded one2many list belong to another model."""
    for ancestor in node.ancestors():
        if ancestor is arch:
            return False
        if ancestor.tag == "field":
            return True
    return False


for _version in (17, 18):
    rule("removed-reference", _version, "error", "xml",
         "Refers to a view, template, model or field that no longer exists (data)")(_removed_xml(_version))


# --- JavaScript --------------------------------------------------------------------

IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s+|\brequire\(\s*)["'](@[\w-]+/[^"']+)["']""")
REQUIRE = re.compile(r"""\brequire\(\s*["']([\w.]+)["']\s*\)""")
FIELD_REGISTRY = re.compile(r"""registry\s*\.category\(\s*["']fields["']\s*\)\s*\.add\(\s*["'][\w.]+["']\s*,\s*([A-Z]\w*)\s*[,)]""")


def _removed_js(version):
    def check(lines):
        data = removed(version)
        for number, line in enumerate(lines, 1):
            for match in IMPORT.finditer(line):
                path = match.group(1)
                if path in data["js_modules"]:
                    hints = data["js_modules"][path]
                    yield (number, match.start(1) + 1, f"Odoo {version} has no JS module {path}.",
                           ("Maybe: " + ", ".join(hints)) if hints else "")
            for match in REQUIRE.finditer(line):
                if match.group(1) in data["legacy_modules"]:
                    yield (number, match.start(1) + 1,
                           f"Odoo {version} has no legacy module '{match.group(1)}': rewrite this file as an ES module.", "")
    return check


for _version in (17, 18):
    rule("removed-js-module", _version, "error", "js", "Imports a JS module that no longer exists (data)")(_removed_js(_version))


@rule("field-registry", 17, "error", "js", "Field widgets are registered as objects")
def field_registry(lines):
    for number, line in enumerate(lines, 1):
        match = FIELD_REGISTRY.search(line)
        if match:
            component = match.group(1)
            yield (number, match.start(1) + 1,
                   "Since Odoo 17 the fields registry holds objects, not components.",
                   f"{{ component: {component} }}")


@rule("env-translate", 17, "error", "js", "env._t was removed")
def env_translate(lines):
    for number, line in enumerate(lines, 1):
        for match in re.finditer(r"\benv\._t\b", line):
            yield (number, match.start() + 1, "Odoo 17 has no env._t.",
                   'import { _t } from "@web/core/l10n/translation";')


@rule("rpc-service", 18, "error", "js", "The rpc service was removed")
def rpc_service(lines):
    for number, line in enumerate(lines, 1):
        for match in re.finditer(r"""useService\(\s*["']rpc["']\s*\)""", line):
            yield (number, match.start() + 1, "Odoo 18 has no rpc service.",
                   'import { rpc } from "@web/core/network/rpc";  then  await rpc(route, params)')
