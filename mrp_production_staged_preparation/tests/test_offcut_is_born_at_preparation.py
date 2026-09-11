# -*- coding: utf-8 -*-
"""Остатъкът се ражда и по пътя на подготовката, не само от ръчния бутон.

Мерено от Владимир на 11.09 — остатъци не се раждат от 08.09:
```
последен offcut лот   08.09 13:06   2080-001
пръв счупен           10.09 15:07   WH/MO/01630 · шарка казва offcut · lot_ids []
stock.move is_staged_offcut: 66, последното 08.09 13:06:31
```
Подателят `action_move_remnants_to_offcut` се викаше само от override-а на
`action_generate_lots` — тоест от РЪЧЕН бутон. Подготовката нарочно не го вика, а
кредит-бекът през страничен продукт е загасен на 09.09. В потока на подготовката
не се задействаше нито един от двата.

⚠️ Тук се изпитва ИЗБОРЪТ (кои разкрои раждат сега). Самото раждане минава през
подателя в плъгина и се доказва на живо.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOffcutIsBornAtPreparation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.gotov = cls.env['product.product'].create({
            'name': 'Offcut birth finished', 'is_storable': True})
        cls.komponent = cls.env['product.product'].create({
            'name': 'Offcut birth bar', 'is_storable': True})
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.gotov.product_tmpl_id.id, 'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.komponent.id, 'product_qty': 1.0})]})

    def _opt(self, mode='transfer', state='done'):
        opt = self.env['mrp.cutting.optimization'].create({
            'name': 'T opt %s %s' % (mode, state),
            'material_domain': 'mrp_production'})
        opt.offcut_birth_mode = mode
        opt.state = state
        return opt

    def _mo(self, opt):
        mo = self.env['mrp.production'].create({
            'product_id': self.gotov.id, 'product_qty': 1.0,
            'bom_id': self.bom.id})
        mo.staged_cutting_optimization_id = opt
        return mo

    def test_a_done_transfer_run_is_picked(self):
        """🔑 Същината: приключил разкрой в режим „transfer" ражда остатък."""
        opt = self._opt()
        mo = self._mo(opt)
        self.assertIn(opt, mo._staged_offcut_opts())

    def test_another_birth_mode_is_left_alone(self):
        """⛔ Друг режим — не е наша работа. Кредит-бекът е загасен нарочно."""
        for mode in ('byproduct', 'inventory'):
            opt = self._opt(mode=mode)
            mo = self._mo(opt)
            self.assertNotIn(opt, mo._staged_offcut_opts(),
                             "режим %s не бива да се пипа" % mode)

    def test_an_unfinished_run_is_not_touched(self):
        """Неприключил разкрой няма остатъци — няма и какво да ражда."""
        opt = self._opt(state='draft')
        mo = self._mo(opt)
        self.assertFalse(mo._staged_offcut_opts())

    def test_without_a_run_nothing_is_selected(self):
        """Поръчка без разкрой — изборът е празен, без грешка."""
        mo = self.env['mrp.production'].create({
            'product_id': self.gotov.id, 'product_qty': 1.0,
            'bom_id': self.bom.id})
        self.assertFalse(mo._staged_offcut_opts())

    def test_one_run_shared_by_two_orders_is_listed_once(self):
        """🔑 Веднъж на РАЗКРОЙ, не на поръчка — инак подателят се вика двойно."""
        opt = self._opt()
        mo1, mo2 = self._mo(opt), self._mo(opt)
        izbor = (mo1 | mo2)._staged_offcut_opts()
        self.assertEqual(len(izbor), 1)
