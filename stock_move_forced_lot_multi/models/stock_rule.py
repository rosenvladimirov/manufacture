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

import logging

from odoo import api, models
from odoo.tools.float_utils import float_compare, float_round

_logger = logging.getLogger(__name__)


class StockRule(models.Model):
    _inherit = "stock.rule"

    # ------------------------------------------------------------ move values

    def _get_stock_move_values(
        self,
        product_id,
        product_qty,
        product_uom,
        location_dest_id,
        name,
        origin,
        company_id,
        values,
    ):
        """Пренася forced_lot_ids от набавянето в създаваното движение."""
        move_values = super()._get_stock_move_values(
            product_id,
            product_qty,
            product_uom,
            location_dest_id,
            name,
            origin,
            company_id,
            values,
        )
        forced_lots = values.get("forced_lot_ids")
        if forced_lots:
            lot_ids = forced_lots.ids if hasattr(forced_lots, "ids") else list(forced_lots)
            move_values["forced_lot_ids"] = [(6, 0, lot_ids)]
        return move_values

    # ------------------------------------------------------------ PO merge

    @api.model
    def _get_procurements_to_merge_groupby(self, procurement):
        """Prevent merging procurements with different forced_lot_ids."""
        # 19: purchase_stock/models/stock_rule.py:242 — ключът е кортеж.
        base_key = super()._get_procurements_to_merge_groupby(procurement)
        forced_lot_ids = procurement.values.get("forced_lot_ids")
        if forced_lot_ids:
            ids = forced_lot_ids.ids if hasattr(forced_lot_ids, "ids") else list(forced_lot_ids)
            lot_key = frozenset(ids)
        else:
            lot_key = frozenset()
        if not isinstance(base_key, tuple):
            base_key = (base_key,)
        return base_key + (lot_key,)

    def _update_purchase_order_line(
        self, product_id, product_qty, product_uom, company_id, values, line
    ):
        """Add forced_lot_ids from values to the existing PO line on merge.

        Core Odoo's ``_update_purchase_order_line`` only carries ``product_qty``,
        ``price_unit`` and ``move_dest_ids`` forward — forced lots from the
        incoming procurement would be dropped. Here we append them to the
        line (Command.link, so existing lots stay) and extend ``name`` with
        the new lot descriptions if they aren't already listed.
        """
        # Сигнатурата е същата в 19: purchase_stock/models/stock_rule.py:298
        res = super()._update_purchase_order_line(
            product_id, product_qty, product_uom, company_id, values, line
        )
        forced_lot_ids = values.get("forced_lot_ids")
        if not forced_lot_ids:
            return res
        if hasattr(forced_lot_ids, "ids"):
            lots = forced_lot_ids
            lot_ids = forced_lot_ids.ids
        else:
            lot_ids = list(forced_lot_ids)
            lots = self.env["stock.lot"].browse(lot_ids)
        new_lot_ids = [lid for lid in lot_ids if lid not in line.forced_lot_ids.ids]
        if not new_lot_ids:
            return res
        res["forced_lot_ids"] = [(4, lid) for lid in new_lot_ids]
        new_lots = lots.filtered(lambda l: l.id in new_lot_ids)
        descriptions = []
        for lot in new_lots:
            desc = lot.name
            if lot.ref:
                desc += f" ({lot.ref})"
            descriptions.append(desc)
        if descriptions:
            existing_name = line.name or ""
            if "\nLots:\n" in existing_name:
                res["name"] = existing_name + "\n" + "\n".join(descriptions)
            else:
                res["name"] = existing_name + "\n\nLots:\n" + "\n".join(descriptions)
        return res

    # ------------------------------------------------------------ split per lot
    #
    # В 18 тази логика живееше в procurement.group.run (models/procurement_group.py).
    # В 19 моделът procurement.group е премахнат и run() е на stock.rule
    # (stock/models/stock_rule.py:453); всички входни точки го викат като
    # self.env['stock.rule'].run(...) — orderpoint (stock_orderpoint.py:750),
    # движения (stock_move.py:1726, mrp/stock_move.py:356), scrap, replenish
    # wizard, връщане. Затова override-ът е тук, със същата семантика.

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
        stock.rule.run (MTO, orderpoint, manual).
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
            # product_uom_qty идва от stock_move_forced_lot_multi_dimension,
            # final_quantity — от project_management_logikal; и двете са
            # по избор, затова getattr.
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

        # В 19 Procurement е NamedTuple в stock/models/stock_rule.py:31,
        # закачен като атрибут на класа (StockRule.Procurement, :56).
        Procurement = self.env["stock.rule"].Procurement
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
