"""List what one Odoo version provides, read from its source code.

    python3 extract.py /path/to/odoo/addons [more addons paths] > odoo-17.json

Runs with the Python of any Odoo version (3.8+), standard library only.
Nothing is imported from Odoo: files are parsed, so no database is needed.
"""

import ast
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

DEFINE = re.compile(r"""odoo\.define\(\s*['"]([^'"]+)['"]""")
ALIAS = re.compile(r"@odoo-module\s+alias=([\w.]+)")


def main(paths):
    data = {"addons": [], "bundles": set(), "js_modules": set(), "legacy_modules": set(),
            "views": set(), "view_models": {}, "templates": set(), "models": {}}
    for addons in map(Path, paths):
        for manifest in sorted(addons.glob("*/__manifest__.py")):
            addon = manifest.parent
            if addon.name.startswith("test"):
                continue  # Odoo's own test addons are not an API
            data["addons"].append(addon.name)
            data["bundles"] |= set(ast.literal_eval(manifest.read_text(encoding="utf-8")).get("assets", {}))
            read_js(addon, data)
            read_xml(addon, data)
            read_python(addon, data)
    view_models = data["view_models"]
    for xmlid in list(view_models):
        seen = set()
        while view_models.get(xmlid, "").startswith("=") and xmlid not in seen:
            seen.add(xmlid)
            view_models[xmlid] = view_models.get(view_models[xmlid][1:], "")
    data["view_models"] = {k: v for k, v in sorted(view_models.items()) if v and not v.startswith("=")}
    for model in data["models"].values():
        model["fields"] = sorted(model["fields"])
        model["inherit"] = sorted(model["inherit"] - {model["name"]})
        model["inherits"] = sorted(model["inherits"])
    out = {key: sorted(value) if isinstance(value, (set, list)) else value for key, value in data.items()}
    out["models"] = {name: {k: v for k, v in model.items() if k != "name"} for name, model in sorted(data["models"].items())}
    json.dump(out, sys.stdout, indent=0, sort_keys=True)


def read_js(addon, data):
    static = addon / "static"
    for path in static.rglob("*.js") if static.is_dir() else ():
        relative = path.relative_to(static).parts
        if "lib" in relative or "tests" in relative:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        data["legacy_modules"] |= set(DEFINE.findall(text)) | set(ALIAS.findall(text))
        if relative[0] == "src":
            name = "/".join(relative[1:])[: -len(".js")]
            data["js_modules"].add(f"@{addon.name}/{name}")


def read_xml(addon, data):
    for path in addon.rglob("*.xml"):
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError:
            continue
        static = "static" in path.relative_to(addon).parts
        for node in root.iter():
            if static:
                if node.get("t-name"):
                    data["templates"].add(node.get("t-name"))
                continue
            if node.tag == "template" and node.get("id"):
                data["views"].add(qualify(addon.name, node.get("id")))
            elif node.tag == "record" and node.get("model") == "ir.ui.view" and node.get("id"):
                xmlid = qualify(addon.name, node.get("id"))
                data["views"].add(xmlid)
                model = node.find("field[@name='model']")
                inherit = node.find("field[@name='inherit_id']")
                if model is not None and model.text:
                    data["view_models"][xmlid] = model.text.strip()
                elif inherit is not None and inherit.get("ref"):
                    data["view_models"][xmlid] = "=" + qualify(addon.name, inherit.get("ref"))


def qualify(addon, xmlid):
    return xmlid if "." in xmlid else f"{addon}.{xmlid}"


def read_python(addon, data):
    for path in addon.rglob("*.py"):
        if "tests" in path.relative_to(addon).parts or "migrations" in path.relative_to(addon).parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                read_model(node, data)


def read_model(node, data):
    attrs = {}
    fields = set()
    for statement in node.body:
        # "name = fields.Char()" and, since 18, "name: Type = fields.Char()"
        # "a = b = value" and, since 18, "name: Type = fields.Char()"
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
        else:
            continue
        value = statement.value
        for name in (target.id for target in targets if isinstance(target, ast.Name)):
            if name in ("_name", "_inherit", "_inherits"):
                try:
                    attrs[name] = ast.literal_eval(value)
                except ValueError:
                    pass
            elif isinstance(value, ast.Call) and is_field(value.func):
                fields.add(name)
    inherit = attrs.get("_inherit") or []
    inherit = [inherit] if isinstance(inherit, str) else list(inherit)
    name = attrs.get("_name") or (inherit[0] if len(inherit) == 1 else None)
    if not isinstance(name, str):
        return
    model = data["models"].setdefault(name, {"name": name, "fields": set(), "inherit": set(), "inherits": set()})
    model["fields"] |= fields
    model["inherit"] |= set(inherit)
    if isinstance(attrs.get("_inherits"), dict):
        model["inherits"] |= set(attrs["_inherits"])


def is_field(func):
    """fields.Char(...) or Char(...) imported from odoo.fields."""
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "fields":
        return func.attr[:1].isupper()
    return False


if __name__ == "__main__":
    main(sys.argv[1:])
