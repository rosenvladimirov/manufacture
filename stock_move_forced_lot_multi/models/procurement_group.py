# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import api, models
from odoo.tools.float_utils import float_compare, float_round

_logger = logging.getLogger(__name__)


class ProcurementGroup(models.Model):
    _inherit = "procurement.group"

    @api.model
    def run(self, procurements, raise_user_error=True):
        """Split forced_lot_ids lots flagged `force_split` or `po_split` into
        their own procurement.

        - `force_split` — qty taken from `stock.lot.split_buffer_qty` (version
          / position lots with an explicit buffer sized at import time).
        - `po_split` — qty = `procurement.product_qty / po_split_count`
          (parent qty split evenly across every po_split lot on this
          procurement). Keeps the total equal to the parent qty regardless of
          cumulative `final_quantity` growth across imports. Used by shared
          glass lots so each lot lands on its own PO line.

        Lots without any split flag stay attached to the parent procurement —
        parent qty is preserved. Works for every flow that enters
        procurement.group.run (MTO, orderpoint, manual).
        """
        expanded = self._split_forced_lot_procurements(procurements)
        return super().run(expanded, raise_user_error=raise_user_error)

    @api.model
    def _get_split_qty_for_lot(self, lot, procurement, po_split_count):
        """Return the qty to carve out of the parent procurement for `lot`.

        Preference order:
        1. `force_split` → `split_buffer_qty` (explicit per-lot buffer;
           version / position lots sized at import time).
        2. `po_split` with per-position usage record →
           `product_uom_qty * usage.pieces` (per-MO need: брой пиеси от лота
           в позицията на това procurement, не project-total). Изисква
           `procurement.values['logikal_position_id']` и наличен модел
           `logikal.lot.position.usage` (модулът `project_management_logikal`).
        3. `po_split` with per-piece dimensions → `product_uom_qty * final_quantity`
           (legacy fallback: works когато няма usage запис).
        4. `po_split` fallback → `procurement.product_qty / po_split_count`
           (evenly split among all po_split lots on this procurement).

        Note: lot-level orderpoints carry a single forced_lot already; they
        do not enter this split path because nothing is to be carved out.
        """
        if lot.force_split and lot.split_buffer_qty:
            return lot.split_buffer_qty
        if lot.po_split:
            product_uom_qty = getattr(lot, "product_uom_qty", 0.0) or 0.0
            if product_uom_qty:
                Usage = self.env.get("logikal.lot.position.usage")
                position_id = procurement.values.get("logikal_position_id") if procurement.values else None
                if Usage is not None and position_id:
                    pid = position_id.id if hasattr(position_id, "id") else position_id
                    usage = Usage.sudo().search(
                        [("lot_id", "=", lot.id), ("position_id", "=", pid)],
                        limit=1,
                    )
                    if usage and usage.pieces:
                        return product_uom_qty * usage.pieces
            final_quantity = getattr(lot, "final_quantity", 0.0) or 0.0
            if product_uom_qty and final_quantity:
                return product_uom_qty * final_quantity
            if po_split_count:
                return procurement.product_qty / po_split_count
        return 0.0

    @api.model
    def _split_forced_lot_procurements(self, procurements):
        if not procurements:
            return procurements

        Procurement = self.Procurement
        result = []

        for procurement in procurements:
            forced_lot_ids = procurement.values.get("forced_lot_ids")
            if not forced_lot_ids:
                result.append(procurement)
                continue

            if hasattr(forced_lot_ids, "ids"):
                lots = forced_lot_ids
            else:
                lots = self.env["stock.lot"].browse(list(forced_lot_ids))

            separate_lots = lots.filtered(lambda l: l.force_split or l.po_split)
            remaining_lots = lots - separate_lots

            if not separate_lots:
                result.append(procurement)
                continue

            po_split_count = len(separate_lots.filtered(
                lambda l: l.po_split and not (l.force_split and l.split_buffer_qty)
            ))

            split_total_qty = 0.0
            for lot in separate_lots:
                qty = self._get_split_qty_for_lot(lot, procurement, po_split_count)
                if qty <= 0:
                    _logger.warning(
                        "Skipping forced lot %s on procurement for %s: "
                        "force_split=%s po_split=%s but derived qty=0 "
                        "(split_buffer_qty=%s, po_split_count=%s, "
                        "parent_qty=%s)",
                        lot.display_name,
                        procurement.product_id.display_name,
                        lot.force_split,
                        lot.po_split,
                        lot.split_buffer_qty,
                        po_split_count,
                        procurement.product_qty,
                    )
                    continue

                split_total_qty += qty
                lot_values = dict(procurement.values)
                lot_values["forced_lot_ids"] = lot
                result.append(Procurement(
                    product_id=procurement.product_id,
                    product_qty=qty,
                    product_uom=procurement.product_uom,
                    location_id=procurement.location_id,
                    name=procurement.name,
                    origin=procurement.origin,
                    company_id=procurement.company_id,
                    values=lot_values,
                ))

            rounding = procurement.product_uom.rounding
            parent_remaining_qty = float_round(
                procurement.product_qty - split_total_qty,
                precision_rounding=rounding,
            )

            if float_compare(parent_remaining_qty, 0.0, precision_rounding=rounding) > 0:
                parent_values = dict(procurement.values)
                parent_values["forced_lot_ids"] = remaining_lots
                result.append(Procurement(
                    product_id=procurement.product_id,
                    product_qty=parent_remaining_qty,
                    product_uom=procurement.product_uom,
                    location_id=procurement.location_id,
                    name=procurement.name,
                    origin=procurement.origin,
                    company_id=procurement.company_id,
                    values=parent_values,
                ))
                _logger.info(
                    "Split procurement for %s: %d separate lot(s), "
                    "parent reduced to %s (was %s), %d remaining lot(s) on parent",
                    procurement.product_id.display_name,
                    len(separate_lots),
                    parent_remaining_qty,
                    procurement.product_qty,
                    len(remaining_lots),
                )
            else:
                _logger.info(
                    "Split procurement for %s: %d separate lot(s) "
                    "cover full qty %s — parent procurement dropped",
                    procurement.product_id.display_name,
                    len(separate_lots),
                    procurement.product_qty,
                )

        return result
