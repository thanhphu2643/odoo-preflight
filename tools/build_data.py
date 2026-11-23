"""Compare the API of consecutive Odoo versions and write what disappeared.

    python3 tools/build_data.py            # extracts from the odoo:16/17/18 Docker images
    python3 tools/build_data.py --cached   # reuses tools/api/odoo-*.json

For each upgrade (16 -> 17, 17 -> 18) it writes src/odoo_upgrade_check/data/upgrade-<to>.json
with the addons, asset bundles, JS modules, views, templates, models and fields that the
older version had and the newer one does not.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "tools" / "api"
OUT = ROOT / "src" / "odoo_upgrade_check" / "data"
VERSIONS = (16, 17, 18)
ADDONS = "/usr/lib/python3/dist-packages/odoo/addons"
# Every model has these; some versions also declare them explicitly.
MAGIC_FIELDS = {"id", "display_name", "create_uid", "create_date", "write_uid", "write_date", "__last_update"}


def extract(version):
    path = API / f"odoo-{version}.json"
    if "--cached" not in sys.argv:
        output = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{ROOT / 'tools'}:/tools:ro", "--entrypoint", "python3",
             f"odoo:{version}", "/tools/extract.py", ADDONS],
            check=True, capture_output=True, text=True,
        ).stdout
        API.mkdir(exist_ok=True)
        path.write_text(output, encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def all_fields(models):
    """Fields of each model, including those of its mixins (_inherit) and delegations (_inherits)."""
    cache = {}

    def resolve(name, seen=()):
        if name in cache:
            return cache[name]
        model = models.get(name)
        if model is None or name in seen:
            return set()
        fields = set(model["fields"])
        for parent in model["inherit"] + model["inherits"]:
            fields |= resolve(parent, seen + (name,))
        cache[name] = fields
        return fields

    return {name: resolve(name) for name in models}


def basename_index(modules):
    index = {}
    for module in modules:
        index.setdefault(module.rsplit("/", 1)[-1], []).append(module)
    return index


def diff(old, new):
    new_js = set(new["js_modules"])
    by_basename = basename_index(new_js)
    old_fields, new_fields = all_fields(old["models"]), all_fields(new["models"])
    return {
        "addons": sorted(set(old["addons"]) - set(new["addons"])),
        "bundles": sorted(set(old["bundles"]) - set(new["bundles"])),
        "legacy_modules": sorted(set(old["legacy_modules"]) - set(new["legacy_modules"])),
        # Moved modules usually keep their file name: offer the new paths as hints.
        "js_modules": {
            module: sorted(by_basename.get(module.rsplit("/", 1)[-1], []))[:3]
            for module in sorted(set(old["js_modules"]) - new_js)
        },
        "views": sorted(set(old["views"]) - set(new["views"])),
        "templates": sorted(set(old["templates"]) - set(new["templates"])),
        "models": sorted(set(old["models"]) - set(new["models"])),
        # Model of the standard views, for those whose model lost fields (to check inheriting views).
        "view_models": {
            view: model for view, model in old["view_models"].items()
            if model in old_fields and model in new_fields and old_fields[model] - new_fields[model] - MAGIC_FIELDS
        },
        "fields": {
            model: sorted(fields - new_fields[model] - MAGIC_FIELDS)
            for model, fields in sorted(old_fields.items())
            if model in new_fields and fields - new_fields[model] - MAGIC_FIELDS
        },
    }


def main():
    apis = {version: extract(version) for version in VERSIONS}
    OUT.mkdir(exist_ok=True)
    for old, new in zip(VERSIONS, VERSIONS[1:]):
        result = diff(apis[old], apis[new])
        (OUT / f"upgrade-{new}.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{old} -> {new}: " + ", ".join(f"{len(value)} {key}" for key, value in result.items()))


if __name__ == "__main__":
    main()
