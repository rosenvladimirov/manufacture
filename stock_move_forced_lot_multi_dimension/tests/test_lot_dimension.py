# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLotDimension(TransactionCase):
    """Парчета по размерите на лота върху PO ред — 19 без uom.category."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_m2 = cls.env.ref("uom.product_uom_square_meter")
        cls.uom_m = cls.env.ref("uom.product_uom_meter")
        # cm е неактивна в данните на 19, но е роднина на m (обща референция mm)
        cls.uom_cm = cls.env.ref("uom.product_uom_cm")
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.partner = cls.env["res.partner"].create({"name": "Glass Vendor"})
        cls.glass = cls.env["product.product"].create({
            "name": "Glass pane",
            "is_storable": True,
            "tracking": "lot",
            "uom_id": cls.uom_m2.id,
        })
        cls.bar = cls.env["product.product"].create({
            "name": "Aluminium bar",
            "is_storable": True,
            "tracking": "lot",
            "uom_id": cls.uom_m.id,
        })
        cls.po = cls.env["purchase.order"].create({"partner_id": cls.partner.id})

    def _line(self, product, qty, uom, **extra):
        vals = {
            "order_id": self.po.id,
            "product_id": product.id,
            "product_qty": qty,
            "product_uom_id": uom.id,
            "price_unit": 1.0,
        }
        vals.update(extra)
        return self.env["purchase.order.line"].create(vals)

    def _lot(self, product, name, **dims):
        return self.env["stock.lot"].create(
            dict(name=name, product_id=product.id, **dims)
        )

    def test_square_meter_pieces_from_lot(self):
        """10 m² при лот 1000×500 mm (0.5 m²) → 20 парчета."""
        lot = self._lot(self.glass, "G-1", width=1000.0, height=500.0)
        line = self._line(self.glass, 10.0, self.uom_m2, forced_lot_ids=[(6, 0, lot.ids)])
        self.assertAlmostEqual(line.lot_pcs_qty, 20.0)

    def test_square_meter_pieces_from_line_dims(self):
        """Без лотове се ползват размерите от самия ред."""
        line = self._line(self.glass, 3.0, self.uom_m2, lot_width=1000.0, lot_height=1000.0)
        self.assertAlmostEqual(line.lot_pcs_qty, 3.0)

    def test_mixed_lot_areas_give_zero(self):
        """Лотове с различна площ → няма еднозначна площ → 0."""
        lot_a = self._lot(self.glass, "G-A", width=1000.0, height=500.0)
        lot_b = self._lot(self.glass, "G-B", width=1000.0, height=1000.0)
        line = self._line(
            self.glass, 10.0, self.uom_m2, forced_lot_ids=[(6, 0, (lot_a | lot_b).ids)]
        )
        self.assertEqual(line.lot_pcs_qty, 0.0)

    def test_meter_pieces_from_bar_length(self):
        """10 m при пръчка 2000 mm → 5 парчета."""
        lot = self._lot(self.bar, "B-1", width=2000.0, height=60.0)
        line = self._line(self.bar, 10.0, self.uom_m, forced_lot_ids=[(6, 0, lot.ids)])
        self.assertAlmostEqual(line.lot_pcs_qty, 5.0)

    def test_related_uom_converted(self):
        """1000 cm (роднина на m по референция) при пръчка 2 m → 5 парчета."""
        lot = self._lot(self.bar, "B-2", width=2000.0, height=60.0)
        line = self._line(self.bar, 1000.0, self.uom_cm, forced_lot_ids=[(6, 0, lot.ids)])
        self.assertAlmostEqual(line.lot_pcs_qty, 5.0)

    def test_unrelated_uom_gives_zero(self):
        """Единица извън m²/m (Units) → 0, без „сляпо“ преобразуване."""
        lot = self._lot(self.glass, "G-U", width=1000.0, height=500.0)
        line = self._line(self.glass, 10.0, self.uom_unit, forced_lot_ids=[(6, 0, lot.ids)])
        self.assertEqual(line.lot_pcs_qty, 0.0)

    def test_update_qty_from_lots_if_area(self):
        lot = self._lot(self.glass, "G-Q", width=1000.0, height=500.0)
        line = self._line(self.glass, 10.0, self.uom_m2, forced_lot_ids=[(6, 0, lot.ids)])
        vals = line._update_qty_from_lots_if_area({"product_qty": 4.0})
        self.assertAlmostEqual(vals["product_qty"], 8.0)
        # Несвързана единица → vals остават непокътнати
        vals = line._update_qty_from_lots_if_area(
            {"product_qty": 4.0, "product_uom_id": self.uom_unit.id}
        )
        self.assertEqual(vals["product_qty"], 4.0)

    def test_po_split_total_area_without_po_split(self):
        """Без po_split лотове → None (стандартното поведение на purchase_stock)."""
        lot = self._lot(self.glass, "G-N", width=1000.0, height=500.0)
        Rule = self.env["stock.rule"]
        self.assertIsNone(Rule._po_split_total_area(self.env["stock.lot"]))
        self.assertIsNone(Rule._po_split_total_area(lot))

    def test_po_split_total_area_fallback_final_quantity(self):
        """po_split лот без usage записи → product_uom_qty × final_quantity."""
        Lot = self.env["stock.lot"]
        if "po_split" not in Lot._fields or "final_quantity" not in Lot._fields:
            self.skipTest("po_split / final_quantity не са налични в тази база")
        if self.env.get("logikal.lot.position.usage") is not None:
            self.skipTest("usage моделът е инсталиран — fallback-ът не е изолиран")
        lot = self._lot(
            self.glass, "G-S", width=1000.0, height=500.0,
            po_split=True, product_uom_qty=0.5, final_quantity=7.0,
        )
        self.assertAlmostEqual(self.env["stock.rule"]._po_split_total_area(lot), 3.5)
