# -*- coding: utf-8 -*-
"""Прозорецът за старт показва разкроя (№116, 01.10).

Любо: „тук искам бутон към оптимизацията, за да мога да видя какво се е
получило". Искано още на 16.07 (TG 2128) — планерът пускаше на сляпо.

Тук се пази:
  ① един разкрой за партидата ⇒ прозорецът го знае (пръти, отпадък, схеми);
  ② смесени разкрои ⇒ нищо наслуки — полето е празно;
  ③ „Виж разкроя" отваря ТОЗИ разкрой над прозореца (target=new).
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPrepareWizardCutting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Opt = cls.env['mrp.cutting.optimization']
        cls.opt = Opt.create({'name': 'T116 cut A',
                              'material_domain': 'mrp_production'})
        cls.other = Opt.create({'name': 'T116 cut B',
                                'material_domain': 'mrp_production'})
        product = cls.env['product.product'].create({
            'name': 'T116 door', 'is_storable': True})
        cls.mos = cls.env['mrp.production'].create([
            {'product_id': product.id, 'product_qty': 1.0}
            for _i in range(2)])
        cls.Wiz = cls.env['mrp.production.prepare.wizard']

    def _wizard(self):
        return self.Wiz.create({'production_ids': [(6, 0, self.mos.ids)]})

    def test_one_cutting_run_is_shown(self):
        self.mos.staged_cutting_optimization_id = self.opt
        wiz = self._wizard()
        self.assertEqual(wiz.cutting_optimization_id, self.opt)
        self.assertEqual(wiz.cutting_bars, self.opt.total_bars_used)
        self.assertEqual(wiz.cutting_pattern_count, self.opt.pattern_count)
        self.assertEqual(wiz.cutting_waste_pct, self.opt.waste_percentage)

    def test_mixed_cutting_runs_show_nothing(self):
        self.mos[0].staged_cutting_optimization_id = self.opt
        self.mos[1].staged_cutting_optimization_id = self.other
        self.assertFalse(self._wizard().cutting_optimization_id)

    def test_view_cutting_opens_this_run_over_the_wizard(self):
        self.mos.staged_cutting_optimization_id = self.opt
        action = self._wizard().action_view_cutting()
        self.assertEqual(action['res_model'], 'mrp.cutting.optimization')
        self.assertEqual(action['res_id'], self.opt.id)
        self.assertEqual(action['target'], 'new')
