# -*- coding: utf-8 -*-
"""Поръчка, родена от снабдяването, също получава подготвителен трансфер.

Мерено на 11.09 по WH/MO/01690 и WH/MO/01691 (от OP/00627 и OP/00628):
```
суровините са създадени В СЪЩАТА СЕКУНДА като поръчката (07:02:29),
вече с location_id = WH/Pre-Production · move_orig_ids празно
подготовката: „No preparation transfer was created … no component move
              starts from stock"          ← вярно по буква, но резултатът е блокаж
суровина 0.00 / 8.75 · буфер 0.00 · WH/Stock 10.50 м
Produce → „You need to supply a Lot/Serial Number"
```
Тези поръчки се раждат по СТАНДАРТНИЯ двустъпков път, а подготовката търсеше само
едностъпкови движения, тръгващи от склада, за да ги преражда в пик.

⇒ Мерилото е НЕДОСТИГЪТ срещу буфера, не произходът на движението.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBufferBornGetsAPick(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Loc = cls.env['stock.location']
        cls.stock = Loc.create({'name': 'T stock', 'usage': 'internal'})
        cls.pbm = Loc.create({'name': 'T buffer', 'usage': 'internal'})
        cls.prod_loc = Loc.create({'name': 'T production', 'usage': 'production'})
        cls.product = cls.env['product.product'].create({
            'name': 'Buffer born bar', 'is_storable': True, 'tracking': 'lot',
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'L-6500', 'product_id': cls.product.id,
        })
        gotov = cls.env['product.product'].create({
            'name': 'Buffer born finished', 'is_storable': True})
        bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': gotov.product_tmpl_id.id, 'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.product.id, 'product_qty': 1.0})]})
        cls.mo = cls.env['mrp.production'].create({
            'product_id': gotov.id, 'product_qty': 1.0, 'bom_id': bom.id})
        cls.pg = cls.env['procurement.group'].create({'name': 'T group'})

    def _consumption(self, qty=8.75, reserved=0.0, lot=True):
        """Движение, каквото се ражда при поръчка от снабдяването: буфер → производство."""
        move = self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom': self.product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': self.pbm.id,
            'location_dest_id': self.prod_loc.id,
            'name': 'консумация',
            'procure_method': 'make_to_stock',
        })
        if lot:
            move.forced_lot_ids = [(6, 0, [self.lot.id])]
        return move

    def test_the_pick_is_born_for_the_shortage(self):
        """🔑 Същината: пикът носи ЛИПСАТА и тръгва от склада към буфера."""
        cons = self._consumption(qty=8.75)
        pick = self.mo._staged_create_buffer_pick(
            cons, self.stock, self.pbm, self.pg, False, 8.75)

        self.assertEqual(pick.location_id, self.stock)
        self.assertEqual(pick.location_dest_id, self.pbm)
        self.assertAlmostEqual(pick.product_uom_qty, 8.75, places=2)
        self.assertEqual(pick.procure_method, 'make_to_stock')

    def test_the_pick_is_not_a_raw_move(self):
        """⛔ Пикът не е консумация — инак поръчката би изяла материала двойно."""
        cons = self._consumption()
        pick = self.mo._staged_create_buffer_pick(
            cons, self.stock, self.pbm, self.pg, False, 3.0)

        self.assertFalse(pick.raw_material_production_id)
        self.assertFalse(pick.workorder_id)

    def test_the_pick_is_unchained_and_traced(self):
        """Следата е поле, не верига — както при ④."""
        cons = self._consumption()
        pick = self.mo._staged_create_buffer_pick(
            cons, self.stock, self.pbm, self.pg, False, 3.0)

        self.assertFalse(pick.move_orig_ids)
        self.assertFalse(pick.move_dest_ids)
        self.assertFalse(cons.move_orig_ids, "върната е верига")
        self.assertEqual(cons.staged_pick_move_id, pick)
        self.assertEqual(pick.staged_consumption_ids, cons)

    def test_the_forced_lot_travels_with_the_pick(self):
        """🔴 Без пренасяне пикът би донесъл ДРУГ прът — проследимостта пада тихо."""
        cons = self._consumption(lot=True)
        pick = self.mo._staged_create_buffer_pick(
            cons, self.stock, self.pbm, self.pg, False, 3.0)

        self.assertEqual(pick.forced_lot_ids, cons.forced_lot_ids)
        self.assertEqual(pick.forced_lot_ids, self.lot)
