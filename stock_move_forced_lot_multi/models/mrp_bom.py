# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    default_forced_lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Default Forced Lot",
        domain="[('product_id', '=', product_id)]",
        help="Lot to force on this component's raw move at MO confirm "
        "(reservation only — no split). За ръчни (PRK / не-LogiKal) BoM-ове: "
        "MO-то консумира този компонент само от посочения лот. Празно = "
        "нормално поведение. LogiKal forced lots имат приоритет.",
    )
