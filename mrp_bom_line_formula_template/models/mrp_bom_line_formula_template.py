#  Copyright 2024 Simone Rubino - Aion Tech
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import test_python_expr


class MrpBomLineFormulaTemplate(models.Model):
    _name = "mrp.bom.line.formula.template"
    _description = "BoM Line Quantity Formula Template"
    _order = "name, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
    )
    quantity_formula = fields.Text(
        required=True,
        help="Formula to be evaluated "
        "when generating the quantity "
        "for a production order line.\n"
        "The following values are available:\n"
        "- bom_line: the current BoM line,\n"
        "- operation: the operation where the components are"
        "consumed for current BoM line,\n"
        "- product: the Product of current BoM line,\n"
        "- product_uom: the UoM of the Product of current BoM line,\n"
        "- product_uom_qty: the quantity of the production order line,\n"
        "- production: the production order being created,\n"
        "The computed quantity "
        "must be assigned to the `quantity` variable.",
    )

    @api.constrains("quantity_formula")
    def _constrain_quantity_formula(self):
        for template in self:
            if template.quantity_formula:
                error_message = test_python_expr(
                    expr=template.quantity_formula,
                    mode="exec",
                )
                if error_message:
                    raise ValidationError(error_message)
