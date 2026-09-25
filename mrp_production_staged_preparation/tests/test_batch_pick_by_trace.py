# -*- coding: utf-8 -*-
"""Пикът на партидата се намира по СЛЕДАТА, не по веригата (№93, 25.09).

След ④ (10.09) консумацията не се връзва за пика — `move_orig_ids` е празно,
следата е `staged_pick_move_id`. Блокът за сливане и оразмеряване по плана
търсеше пиковете през `move_orig_ids` и оттогава не намираше нищо:
```
сливани пикинги (Pick Components)   20.08–10.09   14 от 37
                                    след 10.09     2 от 58
разкрой 1138   три пика по недостига 498,96 м, вместо 80 пръта = 520 м
```
Тук се пази:
  ① пикът се намира и по следата, когато веригата е празна;
  ② след сливане (изтрито движение) и оразмеряване (нулирано движение)
    следата се пренасочва към живото движение на пика — инак куката при
    кацане не подсеща консумацията.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBatchPickByTrace(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Loc = cls.env['stock.location']
        cls.src = Loc.create({'name': 'Trace source', 'usage': 'internal'})
        cls.buf = Loc.create({'name': 'Trace buffer', 'usage': 'internal'})
        cls.prod_loc = Loc.create({
            'name': 'Trace production', 'usage': 'production'})
        cls.product = cls.env['product.product'].create({
            'name': 'Trace test bar', 'is_storable': True})
        cls.ptype = cls.env['stock.picking.type'].search(
            [('code', '=', 'internal'),
             ('company_id', 'in', (cls.env.company.id, False))], limit=1)
        cls.MO = cls.env['mrp.production']

    def _move(self, src, dest, qty, picking=None):
        return self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom': self.product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'name': 'trace test',
            'procure_method': 'make_to_stock',
            'picking_id': picking.id if picking else False,
        })

    def _picking(self):
        return self.env['stock.picking'].create({
            'picking_type_id': self.ptype.id,
            'location_id': self.src.id,
            'location_dest_id': self.buf.id,
        })

    def test_the_pick_is_found_by_the_trace(self):
        """① Без верига пикът се намира по `staged_pick_move_id`."""
        pk = self._picking()
        pick = self._move(self.src, self.buf, 6.5, pk)
        cons = self._move(self.buf, self.prod_loc, 6.5)
        cons.staged_pick_move_id = pick.id
        self.assertFalse(cons.move_orig_ids, "постановката: веригата е празна")
        found = self.MO._staged_first_picks(cons, self.buf)
        self.assertEqual(found, pick,
                         "пикът не е намерен — блокът за партидата пак е сляп")

    def test_a_chained_pick_is_still_found(self):
        """① Заварените вързани движения отпреди ④ също се намират."""
        pk = self._picking()
        pick = self._move(self.src, self.buf, 6.5, pk)
        cons = self._move(self.buf, self.prod_loc, 6.5)
        cons.move_orig_ids = [(4, pick.id)]
        self.assertEqual(self.MO._staged_first_picks(cons, self.buf), pick)

    def test_the_trace_follows_the_merged_move(self):
        """② Слято (изтрито) и нулирано движение ⇒ следата отива на живото."""
        pk = self._picking()
        alive = self._move(self.src, self.buf, 13.0, pk)
        zeroed = self._move(self.src, self.buf, 0.0, pk)
        gone = self._move(self.src, self.buf, 6.5, pk)
        cons_a = self._move(self.buf, self.prod_loc, 6.5)
        cons_b = self._move(self.buf, self.prod_loc, 6.5)
        cons_c = self._move(self.buf, self.prod_loc, 6.5)
        cons_a.staged_pick_move_id = alive.id
        cons_b.staged_pick_move_id = zeroed.id
        cons_c.staged_pick_move_id = gone.id
        gone.unlink()                               # като `_merge_moves`
        self.assertFalse(cons_c.staged_pick_move_id.exists(),
                         "постановката: следата е паднала при триенето")
        moved = self.MO._staged_repoint_consumptions(
            pk, cons_a | cons_b | cons_c)
        self.assertEqual(moved, cons_b | cons_c)
        for cons in (cons_a, cons_b, cons_c):
            self.assertEqual(cons.staged_pick_move_id, alive)

    def test_another_product_is_not_a_candidate(self):
        """⛔ Пренасочва се само към СЪЩИЯ продукт."""
        other = self.env['product.product'].create({
            'name': 'Trace other bar', 'is_storable': True})
        pk = self._picking()
        foreign = self.env['stock.move'].create({
            'product_id': other.id, 'product_uom': other.uom_id.id,
            'product_uom_qty': 5.0, 'location_id': self.src.id,
            'location_dest_id': self.buf.id, 'name': 'trace other',
            'picking_id': pk.id})
        cons = self._move(self.buf, self.prod_loc, 6.5)
        moved = self.MO._staged_repoint_consumptions(pk, cons)
        self.assertFalse(moved)
        self.assertFalse(cons.staged_pick_move_id)
        self.assertTrue(foreign.exists())
