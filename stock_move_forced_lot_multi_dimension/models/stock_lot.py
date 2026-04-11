# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    width = fields.Float(string="Width")
    height = fields.Float(string="Height")
    thickness = fields.Float(string="Thickness")
    product_uom_qty = fields.Float(string="Product UoM Qty")
