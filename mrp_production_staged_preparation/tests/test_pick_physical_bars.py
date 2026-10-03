# -*- coding: utf-8 -*-
"""Буферът се мери с ФИЗИЧЕСКИТЕ цели пръти, не с резервираните метри (№120 т.2).

Тест 02.10 (Клаудио, fulltest, M002088 — PRK 237921 ×3):
```
в Pre-Production преди подготовката   2 свободни цели пръта лот 6500 = 13 м
МО-то при потвърждаване резервира      11,58 м от тях
разкрой 1169: рамка                    2 × 6500 + 1 остатък 4630
PC/00505 поиска                        1 × 6500 + 4630
```
⇒ резервираните 11,58 м, закръглени надолу, дават 1 прът, а в буфера стоят 2:
пикът докарва цял прът в повече (6,5 м).

Тук се пази:
  ① буферът = свободното + резервираното от партидата, в ЦЕЛИ пръти (надолу);
  ② резервираното за чуждо МО не е на партидата;
  ③ остатък с друга дължина и старият остатък на партидата не са цели пръти;
  ④ наличност извън буфера не се брои.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPickPhysicalBars(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Loc = cls.env['stock.location']
        cls.buf = Loc.create({'name': 'T120b buffer', 'usage': 'internal'})
        cls.shelf = Loc.create({
            'name': 'T120b shelf', 'usage': 'internal',
            'location_id': cls.buf.id})
        cls.elsewhere = Loc.create({'name': 'T120b stock', 'usage': 'internal'})
        cls.prod_loc = Loc.create({
            'name': 'T120b production', 'usage': 'production'})
        cls.meter = cls.env.ref('uom.product_uom_meter')
        cls.bar = cls.env['product.product'].create({
            'name': 'T120b frame bar', 'is_storable': True, 'tracking': 'lot',
            'uom_id': cls.meter.id, 'uom_po_id': cls.meter.id})
        Lot = cls.env['stock.lot']
        cls.whole = Lot.create({'name': 'T120b-6500', 'product_id': cls.bar.id,
                                'company_id': cls.env.company.id,
                                'bar_length_mm': 6500})
        cls.remnant = Lot.create({'name': 'T120b-4630', 'product_id': cls.bar.id,
                                  'company_id': cls.env.company.id,
                                  'bar_length_mm': 4630})
        cls.MO = cls.env['mrp.production']

    def _consumption(self, qty):
        move = self.env['stock.move'].create({
            'product_id': self.bar.id, 'product_uom': self.bar.uom_id.id,
            'product_uom_qty': qty, 'location_id': self.buf.id,
            'location_dest_id': self.prod_loc.id, 'name': 'T120b',
            'procure_method': 'make_to_stock'})
        move._action_confirm(merge=False)
        return move

    def _stock(self, loc, qty, lot):
        self.env['stock.quant']._update_available_quantity(
            self.bar, loc, qty, lot_id=lot)

    def _whole(self, consumptions, skip=None):
        return self.MO._staged_buffer_whole_bars(
            consumptions, self.bar, self.buf, self.whole, skip)

    def test_m002088_two_bars_count_not_the_reserved_meters(self):
        """13 м в буфера, резервирани 11,58 ⇒ 2 пръта (13 м), не 1."""
        self._stock(self.shelf, 13.0, self.whole)
        mine = self._consumption(11.58)
        mine._action_assign()
        self.assertAlmostEqual(mine.quantity, 11.58, places=6,
                               msg="постановката: МО-то е резервирало 11,58")
        self.assertAlmostEqual(self._whole(mine), 13.0, places=6)
        # планът на целите пръти 13 м ⇒ пикът е нула, не един прът
        self.assertEqual(self.MO._staged_plan_pick_target(13.0, 13.0, 6.5), 0)

    def test_a_started_bar_is_not_whole(self):
        """12 м = 1 цял прът и начат — брои се 1 (6,5 м)."""
        self._stock(self.buf, 12.0, self.whole)
        mine = self._consumption(3.0)
        mine._action_assign()
        self.assertAlmostEqual(self._whole(mine), 6.5, places=6)

    def test_a_foreign_reservation_is_not_the_batch(self):
        self._stock(self.buf, 13.0, self.whole)
        foreign = self._consumption(6.5)
        foreign._action_assign()
        mine = self._consumption(6.5)
        mine._action_assign()
        self.assertAlmostEqual(self._whole(mine), 6.5, places=6,
                               msg="чуждото МО си държи своя прът")

    def test_remnants_and_old_offcuts_are_not_whole_bars(self):
        # два остатъка по 4630 = 9,26 м — без филтъра по дължина биха дали
        # още един „цял прът“ (6,5 + 9,26 = 15,76 ⇒ 2 вместо 1)
        self._stock(self.buf, 6.5, self.whole)
        self._stock(self.buf, 9.26, self.remnant)
        mine = self._consumption(6.5)
        self.assertAlmostEqual(self._whole(mine), 6.5, places=6)
        self.assertEqual(self._whole(mine, self.whole), 0,
                         "лот в skip_lots (старият остатък на партидата) не се брои")

    def test_stock_outside_the_buffer_does_not_count(self):
        self._stock(self.elsewhere, 65.0, self.whole)
        mine = self._consumption(6.5)
        self.assertEqual(self._whole(mine), 0)
