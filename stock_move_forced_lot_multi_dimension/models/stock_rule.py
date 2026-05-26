# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    @staticmethod
    def _po_split_total_area(lots):
        """Връща сумата от product_uom_qty × final_quantity за po_split лотове.

        Връща None ако нито един лот няма po_split — caller fallback-ва към
        стандартното поведение на purchase_stock (acc product_qty).
        Връща None и ако сумата е <= 0 (липсват dimension/quantity данни) —
        пак fallback, за да не set-нем 0 като product_qty.
        """
        po_split_lots = lots.filtered("po_split")
        if not po_split_lots:
            return None
        total = 0.0
        for lot in po_split_lots:
            uom_qty = getattr(lot, "product_uom_qty", 0.0) or 0.0
            final_qty = getattr(lot, "final_quantity", 0.0) or 0.0
            total += uom_qty * final_qty
        if total <= 0:
            return None
        return total

    def _update_purchase_order_line(
        self, product_id, product_qty, product_uom, company_id, values, line
    ):
        """SET (а не accumulate) product_qty за po_split лотове.

        Стандартното поведение на purchase_stock е
        ``line.product_qty + procurement_uom_po_qty``. За glass лотове с
        po_split=True това дава грешен резултат, защото procurement_qty идва
        от per-MO позиция, а PO ред-ът трябва да отразява общата площ
        на лота — независимо колко procurements/MOs минават през него
        (две позиции, споделящи лот → final_quantity натрупва, parent_qty
        не).

        Override-ът заменя product_qty с lot total m²
        (Σ product_uom_qty × final_quantity по всички po_split лотове на
        линията — incoming + вече прикачени).
        """
        res = super()._update_purchase_order_line(
            product_id, product_qty, product_uom, company_id, values, line,
        )
        all_lots = line.forced_lot_ids
        incoming = values.get("forced_lot_ids")
        if incoming:
            if hasattr(incoming, "_name"):
                all_lots = all_lots | incoming
            else:
                all_lots = all_lots | self.env["stock.lot"].browse(list(incoming))
        total_area = self._po_split_total_area(all_lots)
        if total_area is not None:
            res["product_qty"] = total_area
        return res
