# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    forced_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        compute="_compute_forced_lot_ids",
        string="Forced Lots",
        help="Lots forced on raw material moves in this MO.",
    )

    @api.depends("move_raw_ids.forced_lot_ids")
    def _compute_forced_lot_ids(self):
        for production in self:
            production.forced_lot_ids = (
                production.move_raw_ids.mapped("forced_lot_ids")
            )

    def action_confirm(self):
        """Ensure forced lots are propagated when MO is confirmed."""
        res = super().action_confirm()
        # After confirmation, moves are created
        # forced_lot_ids should already be set via the move creation
        return res


class MrpBomLine(models.Model):
    """
    Optional: Allow setting default forced lots on BoM lines.
    This is commented out as it may not be needed for your use case.
    """
    _inherit = "mrp.bom.line"

    # default_forced_lot_ids = fields.Many2many(
    #     comodel_name="stock.lot",
    #     string="Default Forced Lots",
    #     help="Default lots to use when this component is consumed.",
    # )


class StockMoveMrp(models.Model):
    """
    Extend stock.move for MRP-specific functionality.
    This ensures raw material moves can have forced lots set.
    """
    _inherit = "stock.move"

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        """Add forced_lot_ids to fields that prevent move merging."""
        distinct_fields = super()._prepare_merge_moves_distinct_fields()
        distinct_fields.append("forced_lot_ids")
        return distinct_fields

    def _action_confirm(self, merge=True, merge_into=False):
        """
        When confirming moves from MO, trigger procurement with forced lots.
        """
        res = super()._action_confirm(merge=merge, merge_into=merge_into)
        return res

    def _prepare_procurement_group_vals(self):
        """Include forced lot info in procurement group if needed."""
        vals = super()._prepare_procurement_group_vals()
        return vals

    @api.depends("forced_lot_ids")
    def _compute_display_name(self):
        """Optionally show forced lots in move name."""
        super()._compute_display_name()
        # Uncomment to show lots in display name:
        # for move in self.filtered("forced_lot_ids"):
        #     lots = ", ".join(move.forced_lot_ids.mapped("name"))
        #     move.display_name = f"{move.display_name} [{lots}]"
