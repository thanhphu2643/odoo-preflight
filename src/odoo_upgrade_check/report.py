"""Print findings as text, JSON or GitHub Actions annotations."""

import json
import sys

COLORS = {"error": "\033[31m", "warning": "\033[33m", "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m"}


def text(findings, root, modules, out=None):
    out = out or sys.stdout
    color = out.isatty()
    paint = (lambda name, value: f"{COLORS[name]}{value}{COLORS['reset']}") if color else (lambda _name, value: value)
    for finding in findings:
        item = finding.as_dict(root)
        location = f"{item['path']}:{item['line']}:{item['column']}"
        print(f"{paint('bold', location)}  {paint(item['severity'], item['severity'])}  "
              f"{item['message']} {paint('dim', '[' + item['rule'] + ']')}", file=out)
        if item["fix"]:
            for line in item["fix"].splitlines():
                print(f"    {paint('dim', '→')} {line}", file=out)
    errors = sum(f.rule.severity == "error" for f in findings)
    warnings = len(findings) - errors
    print(f"\n{len(modules)} module(s) checked: {errors} error(s), {warnings} warning(s).", file=out)


def as_json(findings, root, modules, out=None):
    out = out or sys.stdout
    json.dump({
        "modules": [str(module.path.relative_to(root)) if module.path.is_relative_to(root) else str(module.path)
                    for module in modules],
        "findings": [finding.as_dict(root) for finding in findings],
    }, out, indent=2, ensure_ascii=False)
    print(file=out)


def github(findings, root, modules, out=None):
    """Workflow commands: the findings show up on the lines of the pull request."""
    out = out or sys.stdout
    def escape(value):
        return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    for finding in findings:
        item = finding.as_dict(root)
        message = item["message"] + (f"\nFix: {item['fix']}" if item["fix"] else "")
        print(f"::{item['severity']} file={item['path']},line={item['line']},col={item['column']},"
              f"title=Odoo {item['version']}: {item['rule']}::{escape(message)}", file=out)
    text(findings, root, modules, out)


FORMATS = {"text": text, "json": as_json, "github": github}
