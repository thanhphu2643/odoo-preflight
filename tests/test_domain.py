import unittest

from odoo_preflight.domain import Unsupported, attrs_to_attributes, domain_to_expression, states_to_invisible


class TestDomain(unittest.TestCase):
    def test_leaves(self):
        self.assertEqual(domain_to_expression("[('state', '!=', 'draft')]"), "state != 'draft'")
        self.assertEqual(domain_to_expression("[('a', '=', 1)]"), "a == 1")
        self.assertEqual(domain_to_expression("[('a', '=', False)]"), "not a")
        self.assertEqual(domain_to_expression("[('a', '!=', False)]"), "a")
        self.assertEqual(domain_to_expression("[('a', 'in', ['x', 'y'])]"), "a in ['x', 'y']")
        self.assertEqual(domain_to_expression("[('a', '<=', parent.limit)]"), "a <= parent.limit")

    def test_operators(self):
        self.assertEqual(domain_to_expression("[('a', '=', 1), ('b', '=', 2)]"), "a == 1 and b == 2")
        self.assertEqual(domain_to_expression("['|', ('a', '=', 1), ('b', '=', 2)]"), "a == 1 or b == 2")
        self.assertEqual(domain_to_expression("[('c', '=', 3), '|', ('a', '=', 1), ('b', '=', 2)]"),
                         "c == 3 and (a == 1 or b == 2)")
        self.assertEqual(domain_to_expression("['!', '|', ('a', '=', 1), ('b', '=', 2)]"),
                         "not (a == 1 or b == 2)")
        self.assertEqual(domain_to_expression("[]"), "1")

    def test_attrs(self):
        self.assertEqual(
            attrs_to_attributes("{'invisible': [('state', '=', 'done')], 'required': [('type', '=', 'out')]}"),
            {"invisible": "state == 'done'", "required": "type == 'out'"},
        )
        with self.assertRaises(Unsupported):
            attrs_to_attributes("{'invisible': [('name', 'ilike', 'x')]}")

    def test_states(self):
        self.assertEqual(states_to_invisible("draft"), "state != 'draft'")
        self.assertEqual(states_to_invisible("draft, sent"), "state not in ('draft', 'sent')")


if __name__ == "__main__":
    unittest.main()
