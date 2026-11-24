"""Modules, files, rules and findings."""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.parsers import expat

SKIP_DIRS = {"node_modules", "lib", "migrations", "upgrades", "__pycache__", ".git"}


@dataclass(frozen=True)
class Rule:
    id: str
    version: int  # first Odoo version where the code breaks or is deprecated
    severity: str  # "error": fails in that version; "warning": deprecated or silently ignored
    kind: str  # "python", "xml", "js" or "manifest"
    summary: str
    check: object


@dataclass
class Finding:
    rule: Rule
    path: Path
    line: int
    column: int
    message: str
    fix: str = ""

    def as_dict(self, root):
        return {
            "rule": self.rule.id, "severity": self.rule.severity, "version": self.rule.version,
            "path": str(self.path.relative_to(root)) if self.path.is_relative_to(root) else str(self.path),
            "line": self.line, "column": self.column, "message": self.message, "fix": self.fix,
        }


RULES = []


def rule(id, version, severity, kind, summary):
    """Register a check. It receives a parsed file and yields (line, column, message, fix)."""
    def register(check):
        RULES.append(Rule(id, version, severity, kind, summary, check))
        return check
    return register


@dataclass
class Module:
    path: Path
    manifest: dict

    @property
    def name(self):
        return self.path.name

    @property
    def series(self):
        """16 for "16.0.1.0.0", None when the version does not say."""
        match = re.match(r"(\d+)\.0\.", str(self.manifest.get("version", "")))
        return int(match.group(1)) if match else None


def find_modules(paths):
    for path in paths:
        path = Path(path).resolve()
        manifests = [path / "__manifest__.py"] if (path / "__manifest__.py").exists() else sorted(path.rglob("__manifest__.py"))
        for manifest in manifests:
            if SKIP_DIRS.isdisjoint(manifest.relative_to(path).parts[:-1]):
                yield Module(manifest.parent, read_manifest(manifest))


def read_manifest(path):
    try:
        value = ast.literal_eval(path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def module_files(module):
    for path in sorted(module.path.rglob("*")):
        relative = path.relative_to(module.path).parts
        if not path.is_file() or not SKIP_DIRS.isdisjoint(relative[:-1]):
            continue
        if path.suffix == ".py" and path.name != "__manifest__.py":
            yield "python", path
        elif path.suffix == ".xml":
            yield "xml", path
        elif path.suffix == ".js" and relative[0] == "static":
            yield "js", path


# --- XML with line numbers ---------------------------------------------------

@dataclass
class Node:
    tag: str
    attrib: dict
    line: int
    column: int
    parent: "Node" = None
    children: list = field(default_factory=list)
    text: str = ""

    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    @property
    def in_view(self):
        """Inside a view architecture (<field name="arch">) or a QWeb template."""
        return any((node.tag == "field" and node.attrib.get("name") == "arch") or node.tag == "template"
                   for node in self.ancestors())

    @property
    def record_model(self):
        for node in self.ancestors():
            if node.tag == "record":
                return node.attrib.get("model")
        return None


def parse_xml(text):
    parser = expat.ParserCreate()
    root = Node("#document", {}, 0, 0)
    current = [root]

    def start(tag, attrib):
        node = Node(tag, attrib, parser.CurrentLineNumber, parser.CurrentColumnNumber + 1, current[-1])
        current[-1].children.append(node)
        current.append(node)

    def end(_tag):
        current.pop()

    def data(text):
        if not current[-1].children:
            current[-1].text += text

    def no_doctype(*_args):
        raise expat.ExpatError("DOCTYPE is not allowed")  # no entity expansion tricks

    parser.StartElementHandler, parser.EndElementHandler, parser.CharacterDataHandler = start, end, data
    parser.StartDoctypeDeclHandler = parser.EntityDeclHandler = no_doctype
    parser.Parse(text, True)
    return root
