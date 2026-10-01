# -*- coding: utf-8 -*-
"""№117 (Любо, 01.10): редът на Pick Components носи опаковката-прът.

PC/00458 (18-те МО на армировките): редовете се раждаха без опаковка ⇒
складът виждаше 420 m, а не 70 пръта по „6000“.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPcBarPackaging(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id), ("pbm_type_id", "!=", False)], limit=1)
        cls.metre = cls.env.ref("uom.product_uom_meter")

    def setUp(self):
        super().setUp()
        if not self.wh:
            self.skipTest("складът няма Pick Components (pbm_type_id)")

    def _product(self, *opakovki):
        p = self.env["product.product"].create({
            "name": "T117 прът", "type": "consu", "is_storable": True,
            "uom_id": self.metre.id, "uom_po_id": self.metre.id})
        for name, qty in opakovki:
            self.env["product.packaging"].create({"name": name, "qty": qty, "product_id": p.id})
        return p

    def _move(self, product, qty=420.0, picking_type=None, **extra):
        pt = picking_type or self.wh.pbm_type_id
        return self.env["stock.move"].create({
            "name": "T117", "product_id": product.id, "product_uom": self.metre.id,
            "product_uom_qty": qty, "picking_type_id": pt.id,
            "location_id": pt.default_location_src_id.id or self.wh.lot_stock_id.id,
            "location_dest_id": pt.default_location_dest_id.id or self.wh.lot_stock_id.id,
            **extra})

    def test_pc_line_gets_the_bar_and_counts_bars(self):
        product = self._product(("6000", 6.0))
        move = self._move(product, 420.0)
        self.assertEqual(move.product_packaging_id.name, "6000")
        self.assertAlmostEqual(move.product_packaging_qty, 70.0)

    def test_a_part_bar_is_shown_not_rounded(self):
        move = self._move(self._product(("6150", 6.15)), 223.5)
        self.assertAlmostEqual(move.product_packaging_qty, 223.5 / 6.15, places=2)

    def test_quantity_update_keeps_the_bar(self):
        product = self._product(("6000", 6.0))
        move = self._move(product, 420.0)
        move.product_uom_qty = 198.0
        self.assertEqual(move.product_packaging_id.name, "6000")
        self.assertAlmostEqual(move.product_packaging_qty, 33.0)

    def test_two_packagings_decide_nothing(self):
        move = self._move(self._product(("6000", 6.0), ("6500", 6.5)))
        self.assertFalse(move.product_packaging_id)

    def test_a_one_unit_packaging_is_not_a_bar(self):
        move = self._move(self._product(("кутия", 1.0)))
        self.assertFalse(move.product_packaging_id)

    def test_other_operations_are_left_alone(self):
        other = self.wh.int_type_id
        move = self._move(self._product(("6000", 6.0)), picking_type=other)
        self.assertFalse(move.product_packaging_id)

    def test_a_hand_set_packaging_is_kept(self):
        """Ръчната опаковка остава — и при смяна на количеството.

        Продуктът има ЕДНА опаковка-прът; ръчната е на ДРУГ продукт със
        същото име, иначе двете опаковки биха спрели правилото и тестът би
        минавал и без защитата.
        """
        product = self._product(("6000", 6.0))
        hand = self.env["product.packaging"].create({
            "name": "ръчна", "qty": 3.0,
            "product_id": self._product(("ръчна", 3.0)).id})
        move = self._move(product, product_packaging_id=hand.id)
        move.product_uom_qty = 198.0
        self.assertEqual(move.product_packaging_id, hand)
