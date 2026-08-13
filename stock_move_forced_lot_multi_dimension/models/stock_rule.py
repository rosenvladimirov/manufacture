# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models
from odoo.tools.float_utils import float_round


class StockRule(models.Model):
    _inherit = "stock.rule"

    @staticmethod
    def _po_split_total_area(lots):
        """Връща общата нужда (m²) за po_split лотове = искано == вложено.

        Количеството за всеки лот = product_uom_qty × Σ(usage.pieces по всички
        позиции на лота). usage.pieces е авторитетната per-position нужда
        (raw_pieces × real_quantity), същата база, която MO-тата влагат — така
        PO ред-ът (искано) съвпада със сумата на вложеното в производството.

        final_quantity (COUNT DISTINCT GlassID от LogiKal) е ненадеждна за
        реалната нужда (не включва real_quantity, дедуплицира размери), затова
        се ползва само като fallback за лотове БЕЗ usage записи (legacy/import
        без position link).

        Връща None ако нито един лот няма po_split, или ако сумата е <= 0 —
        caller fallback-ва към стандартното поведение на purchase_stock.
        """
        po_split_lots = lots.filtered("po_split")
        if not po_split_lots:
            return None
        env = po_split_lots.env
        Usage = env.get("logikal.lot.position.usage")
        total = 0.0
        for lot in po_split_lots:
            uom_qty = getattr(lot, "product_uom_qty", 0.0) or 0.0
            # Реална обща нужда от лота = Σ usage.pieces по всички позиции
            pieces = 0.0
            if Usage is not None:
                usages = Usage.sudo().search([("lot_id", "=", lot.id)])
                pieces = sum(usages.mapped("pieces"))
            # Fallback само ако няма usage записи за този лот
            if not pieces:
                pieces = getattr(lot, "final_quantity", 0.0) or 0.0
            total += uom_qty * pieces
        if total <= 0:
            return None
        # Закръгляме до UoM precision на продукта (m² → 0.01), за да не носи
        # PO ред-ът натрупана float грешка
        product = po_split_lots[:1].product_id
        rounding = product.uom_id.rounding if product and product.uom_id else 0.01
        return float_round(total, precision_rounding=rounding)

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
