# -*- coding: utf-8 -*-
"""Поръчка не излиза от „подготовка" странично, и липсата на трансфер се казва.

Мерено на 10.09 (Клаудио):
```
МО в progress · staged_released False · 12 неразпределени парчета · 0 разкроя
   и достъпен бутон „Produce All"
17 поръчки без подготвителен трансфер, 16 от тях ВЕЧЕ произведени
```
И двете минаваха тихо. Отказът на подготовката поне се вижда; това не.

🔑 `state` в ядрото е ИЗЧИСЛЯЕМО поле — `any(move_raw_ids.picked)` праща
поръчката в progress без да пита `staged_released`. Гард „в прехода" няма къде да
застане, затова се пази ВХОДЪТ: `picked`.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPreparationIsNotSkipped(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.komponent = cls.env['product.product'].create({
            'name': 'Staged component', 'is_storable': True,
        })
        cls.gotov = cls.env['product.product'].create({
            'name': 'Staged finished', 'is_storable': True,
        })
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.gotov.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.komponent.id, 'product_qty': 2.0})],
        })

    def _mo(self):
        mo = self.env['mrp.production'].create({
            'product_id': self.gotov.id,
            'product_qty': 5.0,
            'bom_id': self.bom.id,
        })
        mo.action_confirm()
        return mo

    def test_picked_is_refused_while_unreleased(self):
        """🔑 Същината: неосвободена поръчка в подготовка не приема `picked`."""
        mo = self._mo()
        if not mo.staged_preparation_enabled:
            mo.staged_preparation_enabled = True
        mo.state = 'preparation'
        mo.staged_released = False
        move = mo.move_raw_ids[:1]
        self.assertTrue(move)

        with self.assertRaises(UserError) as hvanato:
            move.picked = True
        self.assertIn('Preparation', str(hvanato.exception))
        # И състоянието НЕ е мръднало.
        self.assertEqual(mo.state, 'preparation')

    def test_a_released_order_is_left_alone(self):
        """✅ Освободената минава — гардът е за неосвободените."""
        mo = self._mo()
        if not mo.staged_preparation_enabled:
            mo.staged_preparation_enabled = True
        mo.state = 'preparation'
        mo.staged_released = True

        mo.move_raw_ids[:1].picked = True   # не гърми
        self.assertTrue(mo.move_raw_ids[0].picked)

    def test_an_unstaged_order_is_left_alone(self):
        """⛔ Обхватът не се разширява: без staged подготовка гардът мълчи."""
        mo = self._mo()
        mo.staged_preparation_enabled = False
        mo.state = 'preparation'
        mo.staged_released = False

        mo.move_raw_ids[:1].picked = True   # не гърми
        self.assertTrue(mo.move_raw_ids[0].picked)

    def test_the_missing_transfer_speaks(self):
        """③ Липсата на подготвителен трансфер оставя следа в чатъра."""
        mo = self._mo()
        broy_predi = len(mo.message_ids)
        mo._staged_note_no_transfer('тестова причина')

        self.assertEqual(len(mo.message_ids), broy_predi + 1)
        telo = mo.message_ids[0].body
        self.assertIn('No preparation transfer was created', telo)
        self.assertIn('тестова причина', telo)
