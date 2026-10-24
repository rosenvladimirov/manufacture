# -*- coding: utf-8 -*-
"""Пикът по плана приспада прътите, които вече са в буфера (№120, 01.10).

Мерено на fulltest, PC/00492 (6 ал. врати, разкрой 1167), рамка PLAWC.38.102:
```
пик по недостига след сливането   209,10 м = 34 пръта
„Пик по план: 209.10 → 227.55“    37 пръта = целият разкрой
в буфера, резервирани за M001999  18,45 м = 3 пръта
```
⇒ 4,05 м отгоре и фалшив backorder при валидиране.

Тук се пази:
  ① пикът = планът − буфера, в цели пръти (нагоре);
  ② буферът покрива всичко ⇒ 0, не минус;
  ③ в буфера се брои само резервираното от консумациите на партидата —
    не чуждото МО, не друг продукт, не старият остатък (свой крак).
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPickMinusBuffer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Loc = cls.env['stock.location']
        cls.buf = Loc.create({'name': 'T120 buffer', 'usage': 'internal'})
        cls.shelf = Loc.create({
            'name': 'T120 shelf', 'usage': 'internal',
            'location_id': cls.buf.id})
        cls.elsewhere = Loc.create({'name': 'T120 stock', 'usage': 'internal'})
        cls.prod_loc = Loc.create({
            'name': 'T120 production', 'usage': 'production'})
        cls.meter = cls.env.ref('uom.product_uom_meter')
        cls.bar = cls.env['product.product'].create({
            'name': 'T120 frame bar', 'is_storable': True, 'tracking': 'lot',
            'uom_id': cls.meter.id, 'uom_po_id': cls.meter.id})
        Lot = cls.env['stock.lot']
        cls.lot = Lot.create({'name': 'T120-6150', 'product_id': cls.bar.id,
                              'company_id': cls.env.company.id})
        cls.old = Lot.create({'name': 'T120-4000', 'product_id': cls.bar.id,
                              'company_id': cls.env.company.id})
        cls.MO = cls.env['mrp.production']

    def _consumption(self, qty, product=None):
        product = product or self.bar
        move = self.env['stock.move'].create({
            'product_id': product.id, 'product_uom': product.uom_id.id,
            'product_uom_qty': qty, 'location_id': self.buf.id,
            'location_dest_id': self.prod_loc.id, 'name': 'T120',
            'procure_method': 'make_to_stock'})
        move._action_confirm(merge=False)
        return move

    def _stock(self, loc, qty, lot):
        self.env['stock.quant']._update_available_quantity(
            self.bar, loc, qty, lot_id=lot)

    # ① и ② — сметката
    def test_the_pick_is_the_plan_minus_the_buffer(self):
        """PC/00492: 227,55 − 18,45 = 209,10 = 34 пръта, не 37."""
        target = self.MO._staged_plan_pick_target(227.55, 18.45, 6.15)
        self.assertAlmostEqual(target, 209.10, places=6)
        self.assertEqual(round(target / 6.15, 6), 34)

    def test_an_empty_buffer_leaves_the_plan(self):
        self.assertAlmostEqual(
            self.MO._staged_plan_pick_target(227.55, 0.0, 6.15), 227.55,
            places=6)

    def test_a_partial_bar_in_the_buffer_rounds_up(self):
        """4 м в буфера не спестяват прът: 223,55 м ⇒ 37 пръта."""
        self.assertAlmostEqual(
            self.MO._staged_plan_pick_target(227.55, 4.0, 6.15), 227.55,
            places=6)

    def test_a_full_buffer_gives_zero_not_minus(self):
        self.assertEqual(
            self.MO._staged_plan_pick_target(12.30, 18.45, 6.15), 0)

    # ③ — какво се брои в буфера
    def test_only_the_batch_reservation_in_the_buffer_counts(self):
        self._stock(self.shelf, 18.45, self.lot)       # поддървото на буфера
        self._stock(self.elsewhere, 50.0, self.lot)    # не е буферът
        mine = self._consumption(30.0)
        mine._action_assign()
        self.assertAlmostEqual(mine.quantity, 18.45, places=6,
                               msg="постановката: резервирано от буфера")
        self.assertAlmostEqual(
            self.MO._staged_buffer_reserved(mine, self.bar, self.buf),
            18.45, places=6)

    def test_a_foreign_mo_reservation_does_not_count(self):
        self._stock(self.buf, 18.45, self.lot)
        foreign = self._consumption(18.45)
        foreign._action_assign()
        mine = self._consumption(30.0)
        mine._action_assign()
        self.assertFalse(mine.quantity, "постановката: чуждото е взело всичко")
        self.assertEqual(
            self.MO._staged_buffer_reserved(mine, self.bar, self.buf), 0)

    def test_another_product_does_not_count(self):
        other = self.env['product.product'].create({
            'name': 'T120 other', 'is_storable': True,
            'uom_id': self.meter.id, 'uom_po_id': self.meter.id})
        self.env['stock.quant']._update_available_quantity(
            other, self.buf, 10.0)
        cons = self._consumption(10.0, other)
        cons._action_assign()
        self.assertEqual(
            self.MO._staged_buffer_reserved(cons, self.bar, self.buf), 0)

    def test_an_old_remnant_in_the_buffer_does_not_count(self):
        """Старият остатък има свой крак — не намалява целите пръти."""
        self._stock(self.buf, 18.45, self.lot)
        self._stock(self.buf, 4.0, self.old)
        mine = self._consumption(30.0)
        mine._action_assign()
        self.assertAlmostEqual(mine.quantity, 22.45, places=6,
                               msg="постановката: и двата лота резервирани")
        self.assertAlmostEqual(
            self.MO._staged_buffer_reserved(
                mine, self.bar, self.buf, self.old), 18.45, places=6)
