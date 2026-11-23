import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from odoo_upgrade_check.cli import main

SAMPLE = Path(__file__).parent / "fixtures" / "sample16"

# (file, line, rule) the sample module must trigger when going from 16 to 18.
EXPECTED = {
    ("__manifest__.py", 3, "manifest-version"),
    ("__manifest__.py", 4, "removed-dependency"),  # note
    ("__manifest__.py", 7, "removed-dependency"),  # point_of_sale.assets
    ("data/cron.xml", 9, "removed-reference"),  # ir.cron.numbercall
    ("models/models.py", 7, "field-states"),
    ("models/models.py", 8, "group-operator"),
    ("models/models.py", 10, "name-get"),
    ("models/models.py", 14, "name-search-signature"),
    ("models/models.py", 14, "name-search-removed"),
    ("models/models.py", 17, "removed-field"),  # @api.depends("qty_done")
    ("models/models.py", 20, "removed-field"),  # self.qty_done
    ("models/models.py", 23, "user-has-groups"),
    ("models/models.py", 25, "access-methods"),
    ("models/models.py", 26, "name-get-call"),
    ("models/models.py", 26, "name-get-removed"),
    ("models/models.py", 27, "removed-field"),  # search([("qty_done", ...)])
    ("models/models.py", 28, "removed-model"),  # mail.channel
    ("models/models.py", 29, "read-group-signature"),
    ("static/src/js/legacy.js", 3, "removed-js-module"),
    ("static/src/js/legacy.js", 4, "removed-js-module"),
    ("static/src/js/widget.js", 6, "removed-js-module"),
    ("static/src/js/widget.js", 11, "rpc-service"),
    ("static/src/js/widget.js", 12, "env-translate"),
    ("static/src/js/widget.js", 16, "field-registry"),
    ("views/views.xml", 7, "removed-reference"),  # xpath on qty_done
    ("views/views.xml", 8, "view-attrs"),
    ("views/views.xml", 9, "view-attrs"),  # states=
    ("views/views.xml", 12, "view-attrs"),  # <attribute name="attrs">
    ("views/views.xml", 21, "list-view"),
    ("views/views.xml", 23, "removed-reference"),  # <field name="qty_done">
    ("views/views.xml", 31, "list-view"),  # view_mode tree
}


def run(*args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main([str(SAMPLE), *args])
    return code, out.getvalue()


class TestRules(unittest.TestCase):
    def findings(self, *args):
        code, output = run("--format", "json", *args)
        return code, json.loads(output)["findings"]

    def test_sample_16_to_18(self):
        code, findings = self.findings("--to", "18")
        self.assertEqual(code, 1)
        found = {(f["path"].split("sample16/")[1], f["line"], f["rule"]) for f in findings}
        self.assertEqual(found, EXPECTED)

    def test_only_rules_up_to_the_target(self):
        _code, findings = self.findings()  # 16 -> 17 by default
        self.assertTrue(findings)
        self.assertTrue(all(f["version"] in (0, 17) for f in findings))

    def test_fixes(self):
        _code, findings = self.findings()
        fixes = {(f["line"], f["rule"]): f["fix"] for f in findings if f["path"].endswith("views.xml")}
        self.assertEqual(fixes[8, "view-attrs"], "invisible=\"state != 'done'\" readonly=\"picked\"")
        self.assertEqual(fixes[9, "view-attrs"], "invisible=\"state not in ('draft', 'assigned')\"")
        self.assertEqual(fixes[12, "view-attrs"],
                         "<attribute name=\"readonly\">state in ['done', 'cancel']</attribute>")

    def test_ignore(self):
        _code, findings = self.findings("--ignore", "view-attrs,manifest-version")
        self.assertFalse({"view-attrs", "manifest-version"} & {f["rule"] for f in findings})

    def test_github_annotations(self):
        _code, output = run("--format", "github")
        self.assertIn("::error file=", output)
        self.assertIn("title=Odoo 17: view-attrs::", output)

    def test_up_to_date_module(self):
        code, output = run("--from", "18", "--to", "18", "--ignore", "manifest-version")
        self.assertEqual(code, 0)
        self.assertIn("0 error(s), 0 warning(s)", output)


if __name__ == "__main__":
    unittest.main()
