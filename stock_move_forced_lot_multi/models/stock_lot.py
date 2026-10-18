# Copyright 2025-2026 Rosen Vladimirov
#
# This file is available under a DUAL LICENSE:
#   1. GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
#      https://www.gnu.org/licenses/agpl-3.0.html
#   2. A commercial license from Rosen Vladimirov, for use without the obligations
#      of the AGPL. See LICENSE-COMMERCIAL.md. Contact: vladimirov.rosen@gmail.com
#
# Unless you hold a valid commercial license, your use of this file is governed
# by the AGPL-3.0-or-later.


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

    # В 19 точността се казва "Product Unit" (uom/data/uom_data.xml:6,
    # запис uom.decimal_product_uom). Старото име "Product Unit of Measure"
    # не съществува и precision_get тихо връща 2 знака.
    split_buffer_qty = fields.Float(
        string="Split Buffer Qty",
        digits="Product Unit",
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
