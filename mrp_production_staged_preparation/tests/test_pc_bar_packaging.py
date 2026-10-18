# -*- coding: utf-8 -*-
"""№117 (Любо, 01.10): редът на Pick Components носи опаковката-прът.

PC/00458 (18-те МО на армировките): редовете се раждаха без опаковка ⇒
складът виждаше 420 m, а не 70 пръта по „6000“.

19: product.packaging отпадна — опаковката е мерна единица в
`product.uom_ids` (relative_uom_id = мярката на продукта, relative_factor =
количеството), а редът я носи в `packaging_uom_id` / `packaging_uom_qty`.
Ядрото попълва `packaging_uom_id` с мярката на реда ⇒ „без опаковка-прът“ =
опаковката е самата мярка на реда. Проверките са същите като в 18.
"""
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import float_round


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

    def _uom(self, name, qty, base=None):
        """Опаковката в 19: мерна единица спрямо мярката на продукта."""
        return self.env["uom.uom"].create({
            "name": name, "relative_factor": qty,
            "relative_uom_id": (base or self.metre).id})

    def _product(self, *opakovki):
        p = self.env["product.product"].create({
            "name": "T117 прът", "type": "consu", "is_storable": True,
            "uom_id": self.metre.id})
        p.uom_ids = [(4, self._uom(name, qty).id) for name, qty in opakovki]
        return p

    def _move(self, product, qty=420.0, picking_type=None, **extra):
        pt = picking_type or self.wh.pbm_type_id
        return self.env["stock.move"].create({
            "product_id": product.id, "product_uom": self.metre.id,
            "product_uom_qty": qty, "picking_type_id": pt.id,
            "location_id": pt.default_location_src_id.id or self.wh.lot_stock_id.id,
            "location_dest_id": pt.default_location_dest_id.id or self.wh.lot_stock_id.id,
            **extra})

    @staticmethod
    def _bar(move):
        """Опаковката-прът на реда (празно, ако е самата мярка на реда)."""
        if move.packaging_uom_id == move.product_uom:
            return move.packaging_uom_id.browse()
        return move.packaging_uom_id

    def test_pc_line_gets_the_bar_and_counts_bars(self):
        product = self._product(("6000", 6.0))
        move = self._move(product, 420.0)
        self.assertEqual(self._bar(move).name, "6000")
        self.assertAlmostEqual(move.packaging_uom_qty, 70.0)

    def test_a_part_bar_is_shown_not_rounded(self):
        move = self._move(self._product(("6150", 6.15)), 223.5)
        # 19: ядрото (`_compute_packaging_uom_qty`) закръгля броя НАГОРЕ до
        # точността на опаковката (0,01) — 36,341… → 36,35. В 18 броят беше
        # сурово частно. Същината се пази: нецелият брой се вижда като дроб,
        # не като 36 или 37 пръта.
        expected = float_round(223.5 / 6.15, precision_rounding=0.01,
                               rounding_method="UP")
        self.assertAlmostEqual(move.packaging_uom_qty, expected, places=6)
        self.assertNotEqual(round(move.packaging_uom_qty), move.packaging_uom_qty)

    def test_quantity_update_keeps_the_bar(self):
        product = self._product(("6000", 6.0))
        move = self._move(product, 420.0)
        move.product_uom_qty = 198.0
        self.assertEqual(self._bar(move).name, "6000")
        self.assertAlmostEqual(move.packaging_uom_qty, 33.0)

    def test_a_move_turned_into_pc_gets_the_bar(self):
        """Пътят на подготовката: суровото движение (M) се ражда с друг вид
        операция и чак после `write` го прави Pick Components."""
        move = self._move(self._product(("6000", 6.0)), 420.0,
                          picking_type=self.wh.int_type_id)
        self.assertFalse(self._bar(move), "постановката")
        move.picking_type_id = self.wh.pbm_type_id
        self.assertEqual(self._bar(move).name, "6000")
        self.assertAlmostEqual(move.packaging_uom_qty, 70.0)

    def test_two_packagings_decide_nothing(self):
        move = self._move(self._product(("6000", 6.0), ("6500", 6.5)))
        self.assertFalse(self._bar(move))

    def test_a_one_unit_packaging_is_not_a_bar(self):
        move = self._move(self._product(("кутия", 1.0)))
        self.assertFalse(self._bar(move))

    def test_other_operations_are_left_alone(self):
        other = self.wh.int_type_id
        move = self._move(self._product(("6000", 6.0)), picking_type=other)
        self.assertFalse(self._bar(move))

    def test_a_hand_set_packaging_is_kept(self):
        """Ръчната опаковка остава — и при смяна на количеството.

        Продуктът има ЕДНА опаковка-прът; ръчната е на ДРУГ продукт със
        същото име, иначе двете опаковки биха спрели правилото и тестът би
        минавал и без защитата.
        """
        product = self._product(("6000", 6.0))
        hand = self._product(("ръчна", 3.0)).uom_ids
        # 19: ядрото преизчислява `packaging_uom_id` при create (зависи от
        # `product_uom`) и подадената стойност не оцелява — проверено в
        # odoo shell. Ръчната опаковка в 19 се слага на ВЕЧЕ създадения ред
        # (както в UI), затова тук — с write след create.
        move = self._move(product)
        move.packaging_uom_id = hand
        move.product_uom_qty = 198.0
        self.assertEqual(move.packaging_uom_id, hand)

    def test_a_glass_unit_in_m2_gets_no_bar(self):
        """№117 т.2 (PC/00499): стъклопакетът в m² с опаковка „2.0 m2“ не е прът."""
        m2 = self.env.ref("uom.product_uom_square_meter")
        glass = self.env["product.product"].create({
            "name": "T117 стъклопакет", "type": "consu", "is_storable": True,
            "uom_id": m2.id})
        glass.uom_ids = [(4, self._uom("2.0 m2", 2.0, base=m2).id)]
        move = self.env["stock.move"].create({
            "product_id": glass.id, "product_uom": m2.id,
            "product_uom_qty": 0.7, "picking_type_id": self.wh.pbm_type_id.id,
            "location_id": self.wh.pbm_type_id.default_location_src_id.id or self.wh.lot_stock_id.id,
            "location_dest_id": self.wh.pbm_type_id.default_location_dest_id.id or self.wh.lot_stock_id.id})
        self.assertFalse(self._bar(move), "стъклопакет получи опаковка-прът")
