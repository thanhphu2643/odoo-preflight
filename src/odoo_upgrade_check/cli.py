import argparse
import sys
from pathlib import Path

from . import __version__, checks  # noqa: F401  (registers the rules)
from .core import RULES, find_modules, module_files, parse_xml
from .report import FORMATS

LATEST = 18


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="odoo-upgrade-check",
        description="Find what breaks when Odoo modules move to a newer version.",
    )
    parser.add_argument("paths", nargs="*", default=["."], help="modules, or folders that contain modules")
    parser.add_argument("--to", type=int, default=None, metavar="VERSION",
                        help=f"target Odoo version (default: the next one, up to {LATEST})")
    parser.add_argument("--from", dest="source", type=int, default=None, metavar="VERSION",
                        help="version the modules are written for (default: from each manifest)")
    parser.add_argument("--format", choices=sorted(FORMATS), default="text")
    parser.add_argument("--ignore", default="", metavar="RULES", help="comma separated rule ids to skip")
    parser.add_argument("--strict", action="store_true", help="exit with an error on warnings too")
    parser.add_argument("--list-rules", action="store_true", help="show the rules and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.list_rules:
        for item in sorted(RULES, key=lambda r: (r.version, r.id)):
            version = f"Odoo {item.version}" if item.version else "any"
            print(f"{item.id:<22} {version:<8} {item.severity:<8} {item.summary}")
        return 0

    root = Path.cwd()
    ignored = {value.strip() for value in args.ignore.split(",") if value.strip()}
    modules = list(find_modules(args.paths))
    if not modules:
        print("No Odoo module found (looking for __manifest__.py).", file=sys.stderr)
        return 2

    findings = []
    for module in modules:
        source = args.source or module.series
        if source is None:
            print(f"{module.name}: cannot tell its Odoo version from the manifest, use --from.", file=sys.stderr)
            return 2
        target = args.to or min(source + 1, LATEST)
        rules = [r for r in RULES if (r.version == 0 or source < r.version <= target) and r.id not in ignored]
        findings += check_module(module, rules, target)

    FORMATS[args.format](findings, root, modules)
    failing = {"error", "warning"} if args.strict else {"error"}
    return 1 if any(f.rule.severity in failing for f in findings) else 0


def check_module(module, rules, target):
    from .core import Finding
    findings = []
    for item in rules:
        if item.kind == "manifest":
            for line, column, message, fix in item.check(module, target):
                findings.append(Finding(item, module.path / "__manifest__.py", line, column, message, fix))
    for kind, path in module_files(module):
        kind_rules = [r for r in rules if r.kind == kind]
        if not kind_rules:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            parsed = parse(kind, source)
        except SyntaxError as error:
            print(f"{path}: skipped, cannot parse ({error})", file=sys.stderr)
            continue
        for item in kind_rules:
            for line, column, message, fix in item.check(parsed):
                findings.append(Finding(item, path, line, column, message, fix))
    return sorted(findings, key=lambda f: (str(f.path), f.line, f.column))


XML_DOCUMENTS = {"odoo", "openerp", "data", "record", "template", "templates", "function", "menuitem"}
# Wraps a bare view architecture on its first line, so line numbers stay the same.
XML_WRAPPER = ('<odoo><record id="snippet" model="ir.ui.view"><field name="arch" type="xml">', "</field></record></odoo>")


def check_source(kind, source, version_from, version_to):
    """Findings for the content of one file (python, xml or js), e.g. pasted in the web page.

    Raises SyntaxError when it cannot be parsed.
    """
    from .core import Finding
    rules = [r for r in RULES if r.kind == kind and r.version and version_from < r.version <= version_to]
    if kind == "xml":
        try:
            parsed = parse(kind, source)
            wrap = not parsed.children or parsed.children[0].tag not in XML_DOCUMENTS
        except SyntaxError:
            wrap = True  # several elements, e.g. a few fields of a view
        if wrap:
            parsed = parse(kind, XML_WRAPPER[0] + source.lstrip("\ufeff") + XML_WRAPPER[1])
    else:
        wrap = False
        parsed = parse(kind, source)
    shift = len(XML_WRAPPER[0]) if wrap else 0
    findings = [Finding(item, Path("snippet"), line, column - shift if line == 1 else column, message, fix)
                for item in rules for line, column, message, fix in item.check(parsed)]
    return sorted(findings, key=lambda f: (f.line, f.column))


def parse(kind, source):
    if kind == "python":
        import ast
        return ast.parse(source)
    if kind == "xml":
        from xml.parsers.expat import ExpatError
        try:
            return parse_xml(source)
        except ExpatError as error:
            raise SyntaxError(str(error)) from error
    return source.splitlines()
