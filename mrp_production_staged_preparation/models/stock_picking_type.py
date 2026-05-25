# Copyright 2026 BL Consulting
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    staged_preparation_enabled = fields.Boolean(
        string="Enable Staged Preparation",
        default=False,
        help=(
            "When enabled on a manufacturing operation type, MOs created with "
            "this picking type start in the 'Intermediate' stage. In this stage "
            "raw component moves and finished goods moves bypass the warehouse "
            "buffer locations (pbm_loc_id / sam_loc_id) and operate directly "
            "against WH/Stock — so the native pull rules do NOT generate "
            "Pick Components / Store Finished pickings, but forecast still "
            "sees the demand because production moves exist в `confirmed`.\n\n"
            "User triggers 'Prepare for Production' button on the MO to "
            "transition to 'Prepared' stage: endpoints се swap-ват към "
            "буферните локации, moves re-confirm-нати, pull rules се eval-ват, "
            "Pick/Store pickings се раждат натurally от Odoo procurement."
        ),
    )
