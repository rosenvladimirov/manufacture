# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    force_split = fields.Boolean(
        string="Split Into Separate Procurement",
        help="When enabled, this forced lot is split off into its own "
        "procurement (MO / PO / any other flow) with requested quantity "
        "taken from `split_buffer_qty`. Unflagged forced lots stay "
        "attached to the parent procurement and do not alter its quantity.",
    )

    split_buffer_qty = fields.Float(
        string="Split Buffer Qty",
        digits="Product Unit of Measure",
        default=0.0,
        help="Requested quantity used when generating the separate "
        "procurement (only when `force_split = True`).",
    )

    po_split = fields.Boolean(
        string="Force PO Line Split",
        help="When enabled, procurements consuming this lot will not merge "
        "into an existing PO line of the same product — a dedicated PO line "
        "with this lot as forced_lot_ids is created instead. Independent "
        "from `force_split`.",
    )
