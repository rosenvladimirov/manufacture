#  Copyright 2024 Simone Rubino - Aion Tech
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class MRPBomLine(models.Model):
    _inherit = "mrp.bom.line"

    formula_template_id = fields.Many2one(
        "mrp.bom.line.formula.template",
        string="Quantity Formula Template",
    )
    quantity_formula = fields.Text(
        compute="_compute_quantity_formula",
        store=True,
        readonly=True,
    )

    @api.depends("formula_template_id", "formula_template_id.quantity_formula")
    def _compute_quantity_formula(self):
        for line in self:
            line.quantity_formula = line.formula_template_id.quantity_formula or False
