from odoo import api, fields, models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    note = fields.Char(states={"done": [("readonly", True)]})
    weight = fields.Float(group_operator="avg")

    def name_get(self):
        return [(line.id, line.reference) for line in self]

    @api.model
    def _name_search(self, name, args=None, operator="ilike", limit=100, name_get_uid=None):
        return super()._name_search(name, args, operator, limit, name_get_uid)

    @api.depends("qty_done")
    def _compute_weight(self):
        for line in self:
            line.weight = self.qty_done

    def totals(self):
        if not self.user_has_groups("stock.group_stock_manager"):
            return []
        self.check_access_rights("read")
        names = self.env["res.partner"].browse(1).name_get()
        lines = self.env["stock.move.line"].search([("qty_done", ">", 0)])
        channel = self.env["mail.channel"].search([], limit=1)
        return self._read_group([], fields=["weight"], groupby=["product_id"], lazy=False)
