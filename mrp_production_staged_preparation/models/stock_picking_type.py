# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
# https://www.odoo.com/documentation/user/legal/licenses/licenses.html

from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    staged_preparation_enabled = fields.Boolean(
        string="Enable Staged Preparation",
        default=False,
        help=(
            "When enabled on a manufacturing operation type, MOs created with "
            "this picking type get a 'Preparation' gate **after** Plan: workorders "
            "are scheduled normally, Pick/Store pickings and PO drafts are born "
            "at confirm time, but the MO sits in 'Preparation' state until "
            "the operator clicks 'Prepare for Production' to release it to the "
            "floor.\n\n"
            "Lifecycle: draft → action_confirm (Pick/PO chain triggers) → "
            "confirmed → button_plan (workorders planned) → preparation (gate) → "
            "action_prepare_production → confirmed → progress → done."
        ),
    )
