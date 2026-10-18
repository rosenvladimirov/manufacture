# -*- coding: utf-8 -*-
"""Бродещият маршрут: staged поръчка не вика снабдяване — нито след ПфП.

Мерено на fulltest (11.09), движения Stock → Pre-Production, родени от правило:
```
правило 136 „Стока → Pre-Production (MTO)"    7
правило 136/146 общо                          17
```
Подготовката не ползва правило изобщо — тя ПРЕРАЖДА суровинното движение
(`rule_id` празно). Тоест всяко движение с правило към буфера е родено зад гърба ѝ.

🔑 Пазачът съществуваше, но спираше при освобождаване на поръчката. Точно там
броди маршрутът: след ПфП движението е Pre-Production → Production, ядрото вижда
правило към тази локация, вдига го на `make_to_order` и снабдяването тръгва.
Така се роди WH/PC/00341 — от смяна на количество по освободена поръчка, при
ПРАЗЕН WH/Stock.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWanderingRouteIsSilenced(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.komponent = cls.env['product.product'].create({
            'name': 'Route test bar', 'is_storable': True,
        })
        cls.gotov = cls.env['product.product'].create({
            'name': 'Route test finished', 'is_storable': True,
        })
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.gotov.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.komponent.id, 'product_qty': 2.0})],
        })

    def _mo(self, staged=True):
        mo = self.env['mrp.production'].create({
            'product_id': self.gotov.id,
            'product_qty': 3.0,
            'bom_id': self.bom.id,
        })
        mo.picking_type_id.staged_preparation_enabled = staged
        mo.action_confirm()
        return mo

    def _raw(self, mo):
        move = mo.move_raw_ids.filtered(
            lambda m: m.product_id == self.komponent)
        self.assertEqual(len(move), 1)
        return move

    def test_before_release_the_move_stays_mts(self):
        """Заварено поведение — пазачът е важал и досега."""
        mo = self._mo()
        mo.staged_released = False
        self.assertTrue(self._raw(mo)._staged_keep_mts())

    def test_after_release_the_move_still_stays_mts(self):
        """🔑 Същината: освобождаването вече НЕ отваря вратата на маршрута.

        Дотук тук се връщаше False, движението ставаше make_to_order и
        правилото раждаше трансфер зад гърба на подготовката.
        """
        mo = self._mo()
        mo.staged_released = True
        self.assertTrue(self._raw(mo)._staged_keep_mts())

    def test_adjust_procure_method_keeps_it_to_stock(self):
        """Поведението, не само предикатът: методът НЕ го вдига на MTO."""
        mo = self._mo()
        mo.staged_released = True
        move = self._raw(mo)
        move.procure_method = 'make_to_order'
        move._adjust_procure_method()
        self.assertEqual(move.procure_method, 'make_to_stock')

    def test_a_non_staged_picking_type_is_left_to_the_core(self):
        """⛔ Обхватът не се разширява — чужд поток не се пипа."""
        mo = self._mo(staged=False)
        mo.staged_released = True
        self.assertFalse(self._raw(mo)._staged_keep_mts())

    def test_glass_is_still_excluded(self):
        """Стъклото си остава извън пазача, както беше."""
        glass_categ = self.env['product.category'].create({'name': 'Glass'})
        self.komponent.categ_id = glass_categ
        mo = self._mo()
        self.assertFalse(self._raw(mo)._staged_keep_mts())
