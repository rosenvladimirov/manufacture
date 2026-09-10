# -*- coding: utf-8 -*-
"""Консумацията не се връзва за трансфера — буферът е ЛОКАЦИЯ, не етап.

Мерено по WH/MO/01641 (10.09): движението иска 1,30 м, стои на 1,03, а в СЪЩАТА
локация, от СЪЩИЯ форсиран лот, лежат 7,02 м свободни. Причината не е наличност:
```
пикът достави   116,25
− 01630 (done)   49,49
− 01631 (done)   65,73
= таван за 01641  1,03     ← точно колкото стои
```
Вързано движение резервира само каквото веригата му е доставила. Доставеше ли
пикът по-малко (непълен трансфер, NO BACKORDER), консумацията остава заключена
под тавана — и отвън не се лекува.

⇒ ④ (Росен, 10.09): веригата пада. Пикът пълни локацията, консумацията взима
оттам. Следата остава в `staged_pick_move_id`, а дораздаването при кацане прави
куката в `_action_done` — native propagation вече няма кой да го стори.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConsumptionIsNotChained(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Loc = cls.env['stock.location']
        cls.src = Loc.create({'name': 'Test source', 'usage': 'internal'})
        cls.buf = Loc.create({'name': 'Test buffer', 'usage': 'internal'})
        # ⚠️ НЕ през външен идентификатор: `stock.location_production` го няма
        # в 18.0 и фикстурата пада на setUpClass, тоест ВСИЧКИ тестове в
        # класа излизат като грешка, а кодът е непроверен.
        cls.prod_loc = Loc.create({
            'name': 'Test production', 'usage': 'production'})
        cls.product = cls.env['product.product'].create({
            'name': 'Chained test bar', 'is_storable': True,
        })
        # Буферът има 3, складът 10. Консумацията иска 5 → 3 сега, 2 от пика.
        Quant = cls.env['stock.quant']
        Quant._update_available_quantity(cls.product, cls.buf, 3.0)
        Quant._update_available_quantity(cls.product, cls.src, 10.0)

    def _move(self, src, dest, qty):
        return self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom': self.product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'name': 'test',
            'procure_method': 'make_to_stock',
        })

    def test_the_trace_field_exists_and_does_not_chain(self):
        """Следата е ПОЛЕ, не верига — `move_orig_ids` остава празно."""
        pick = self._move(self.src, self.buf, 2.0)
        cons = self._move(self.buf, self.prod_loc, 5.0)
        cons.staged_pick_move_id = pick.id

        self.assertEqual(cons.staged_pick_move_id, pick)
        self.assertEqual(pick.staged_consumption_ids, cons)
        self.assertFalse(cons.move_orig_ids, "веригата се е върнала")

    def test_the_consumption_reserves_the_buffer_without_a_chain(self):
        """Разкачената консумация вижда СВОБОДНОТО в локацията."""
        cons = self._move(self.buf, self.prod_loc, 5.0)
        cons._action_confirm(merge=False)
        cons._action_assign()
        # Буферът има 3 → взима 3, не 0. (При верига таванът щеше да е 0.)
        self.assertAlmostEqual(cons.quantity, 3.0, places=2)

    def test_a_landed_pick_tops_up_its_consumption(self):
        """🔑 Същината: щом пикът кацне, консумацията се дорезервира САМА.

        Без куката тя щеше да чака човек да натисне „Check availability" —
        точно чакането, от което тръгнахме.
        """
        cons = self._move(self.buf, self.prod_loc, 5.0)
        cons._action_confirm(merge=False)
        cons._action_assign()
        self.assertAlmostEqual(cons.quantity, 3.0, places=2)

        pick = self._move(self.src, self.buf, 2.0)
        cons.staged_pick_move_id = pick.id
        pick._action_confirm(merge=False)
        pick._action_assign()
        pick.quantity = 2.0
        pick.picked = True
        pick._action_done()

        self.assertEqual(pick.state, 'done')
        # Двете нови бройки са кацнали в буфера и консумацията ги е взела.
        self.assertAlmostEqual(cons.quantity, 5.0, places=2)

    def test_an_unrelated_pick_touches_nothing(self):
        """⛔ Обхватът: пик без следа не размърдва чужди консумации."""
        cons = self._move(self.buf, self.prod_loc, 5.0)
        cons._action_confirm(merge=False)
        cons._action_assign()

        pick = self._move(self.src, self.buf, 2.0)   # БЕЗ staged_pick_move_id
        pick._action_confirm(merge=False)
        pick._action_assign()
        pick.quantity = 2.0
        pick.picked = True
        pick._action_done()

        self.assertAlmostEqual(cons.quantity, 3.0, places=2)
