#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class MrpProductionCoefficientLog(models.Model):
    _name = "mrp.production.coefficient.log"
    _description = "MRP Production Distribution Coefficient Log"
    _order = "create_date desc, id desc"

    move_id = fields.Many2one(
        "stock.move",
        required=True,
        ondelete="cascade",
    )
    production_id = fields.Many2one(
        related="move_id.raw_material_production_id",
        store=True,
    )
    product_id = fields.Many2one(
        related="move_id.product_id",
        store=True,
    )
    product_uom_id = fields.Many2one(
        related="move_id.product_uom",
        store=True,
    )
    coefficient = fields.Float("Distribution Coefficient")
    planned_qty = fields.Float("Planned Qty")
    base_distribution_qty = fields.Float("Base Material Qty")
    user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
    )
    date = fields.Datetime(
        default=fields.Datetime.now,
    )
