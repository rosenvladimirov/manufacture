# -*- coding: utf-8 -*-
"""„Виж разкроя“ при отказ — пробен разкрой, нищо не остава (№116, 01.10).

Любо: „не мога да видя КОИ парчета не влизат, как са подредени прътите и
колко е отпадъкът" — отказът „not enough bar stock … Nothing was committed"
откатва всичко.

Тук се пази:
  ① отказът на гейта носи бутон, а бутонът — МО-тата на партидата;
  ② пробата показва прътите (парчета, остатък) и непобраните (МО, дължина);
  ③ след пробата разкроят го НЯМА в базата — savepoint-ът е откатен;
  ④ проба, която сама отказва, казва своята причина.
"""
from unittest.mock import patch

from odoo.exceptions import RedirectWarning, UserError
from odoo.tests.common import TransactionCase, tagged


class _Bin:
    def __init__(self, pieces, remnant, disposition):
        self.pieces, self.remnant, self.disposition = pieces, remnant, disposition

    def waste(self):
        return self.remnant


@tagged('post_install', '-at_install')
class TestCuttingTrial(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Opt = cls.env['mrp.cutting.optimization']
        cls.OptCls = type(cls.Opt)
        cls.bar = cls.env['product.product'].create({
            'name': 'T116 frame bar', 'is_storable': True})
        door = cls.env['product.product'].create({
            'name': 'T116 door', 'is_storable': True})
        cls.mos = cls.env['mrp.production'].create([
            {'product_id': door.id, 'product_qty': 1.0} for _i in range(2)])
        cls.MO = cls.env['mrp.production']

    def _res(self):
        piece = type('Piece', (), {'production_id': self.mos[1]})()
        bt = {'product_id': self.bar.id, 'length': 6150.0}
        return {
            'bins': [{'bin': _Bin([(5000.0, None), (1000.0, None)], 130.0,
                                  'scrap'), 'bt': bt}],
            'problems_text': 'not enough bar stock: T116',
            'unplaced': [('T116 frame', 1350.0, piece)],
        }

    def _trial(self, run=None):
        run = run or (lambda opt, groups, trial=False: self._res())
        with patch.object(self.OptCls, '_adapter', lambda opt: type(
                'A', (), {'collect_groups': lambda s, o: [{'g': 1}]})()), \
                patch.object(self.OptCls, '_run_optimization', run):
            action = self.MO._staged_cutting_trial_action(self.mos.ids)
        return self.env[action['res_model']].browse(action['res_id'])

    def test_the_refusal_carries_a_button_with_the_orders(self):
        def refuse(opt):
            raise UserError("not enough bar stock")
        # Гейтът реже само МО с парчета; тук МО-тата нямат — филтърът се
        # подменя да ги пусне, за да стигне отказът до обвивката.
        with patch.object(self.OptCls, 'action_optimize', refuse), \
                patch.object(type(self.MO), 'filtered',
                             lambda recs, f: recs):
            with self.assertRaises(RedirectWarning) as cm:
                self.mos._staged_optimize_and_gate()
        message, action_id, button, ctx = cm.exception.args
        self.assertIn("Nothing was committed", message)
        self.assertEqual(action_id, self.env.ref(
            'mrp_production_staged_preparation.action_staged_cutting_trial').id)
        self.assertEqual(ctx, {'staged_trial_mo_ids': self.mos.ids})

    def test_the_trial_shows_bars_and_what_does_not_fit(self):
        wiz = self._trial()
        html = str(wiz.report_html)
        self.assertIn('5000 · 1000', html, "парчетата на пръта")
        self.assertIn('130', html, "остатъкът")
        self.assertIn(self.mos[1].name, html, "МО-то на непобраното")
        self.assertIn('1350', html, "дължината на непобраното")
        self.assertIn('not enough bar stock', wiz.problems_text)

    def test_nothing_of_the_trial_stays(self):
        before = self.Opt.search_count([])
        self._trial()
        self.assertEqual(self.Opt.search_count([]), before,
                         "пробният разкрой остана в базата")

    def test_a_trial_that_refuses_says_why(self):
        def run(opt, groups, trial=False):
            raise UserError("fictitious saw")
        wiz = self._trial(run)
        self.assertEqual(wiz.problems_text, "fictitious saw")
        self.assertFalse(self.Opt.search_count([('name', 'like', 'Trial:')]))

    def test_an_empty_source_says_why(self):
        """Адаптерът не даде групи ⇒ причината, не празен прозорец."""
        adapter = type('A', (), {
            'collect_groups': lambda s, o: [],
            'explain_empty': lambda s, o: "12 pieces on a no-cut saw"})()
        with patch.object(self.OptCls, '_adapter', lambda opt: adapter):
            action = self.MO._staged_cutting_trial_action(self.mos.ids)
        wiz = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wiz.problems_text, "12 pieces on a no-cut saw")
        self.assertFalse(wiz.report_html)
