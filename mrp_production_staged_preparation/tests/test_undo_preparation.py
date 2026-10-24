# -*- coding: utf-8 -*-
"""Undo Preparation при партида (№93, тестът на Клаудио на fulltest, 30.09).

Разкрой 1143 → 11 МО → Undo „Back to Confirmed" → нов разкрой 1151:
  1) PC/00409 не се изтри („Transfers to delete: 0"), новото Prepare се
    сля в него ⇒ ×2 заявено при 71 артикула;
  2) разпределенията на 1143 останаха ⇒ МО-тата сумираха 1143 + 1151 ⇒
    профили ×2 (MO/01814 каса 294,1 = 147,05 + 147,05);
  3) „Back to Confirmed" остави ПЛАНИРАНО МО в confirmed ⇒ няма нито Plan,
    нито Prepare.

Тестът пази, върху ИСТИНСКИЯ PfP (`_staged_do_prepare`) на ДВЕ МО в един разкрой:
  ① двете МО → ЕДИН PC; откатът на двете го изтрива, а консумациите стават
    едностъпкови (Stock → Production), живи, със същото количество;
  ② откат само на едното МО отказва с името на другото — нищо не се пипа;
  ③ разпределенията на отменените МО изчезват, връзката МО → разкрой пада;
  ④ планирано МО се връща в „preparation“, непланирано — в „confirmed“;
  ⑤ визардът брои PC-то (1), не 0.
"""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestUndoPreparation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang='en_US'))
        company = cls.env.company
        Account = cls.env['account.account']

        def acc(code, name):
            return Account.create({'code': code, 'name': name,
                                   'account_type': 'asset_current'})

        journal = cls.env['account.journal'].create({
            'name': 'T93U stock', 'code': 'T93UJ', 'type': 'general'})
        categ = cls.env['product.category'].create({
            'name': 'T93U bars', 'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
            'property_stock_account_input_categ_id': acc('T93UIN', 'in').id,
            'property_stock_account_output_categ_id': acc('T93UOUT', 'out').id,
            'property_stock_valuation_account_id': acc('T93UVAL', 'val').id,
            'property_stock_journal': journal.id,
        })
        relabel = company._get_lot_relabel_location()
        relabel.write({
            'valuation_in_account_id': acc('T93ULIN', 'rel in').id,
            'valuation_out_account_id': acc('T93ULOUT', 'rel out').id,
        })
        cls.meter = cls.env.ref('uom.product_uom_meter')
        cls.bar = cls.env['product.product'].create({
            'name': 'PVC frame T93U', 'is_storable': True, 'tracking': 'lot',
            'categ_id': categ.id,
            'uom_id': cls.meter.id, 'uom_po_id': cls.meter.id})
        cls.window = cls.env['product.product'].create({
            'name': 'Window T93U', 'is_storable': True})
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.window.product_tmpl_id.id,
            'product_qty': 1.0, 'consumption': 'flexible',
            'bom_line_ids': [(0, 0, {
                'product_id': cls.bar.id, 'product_qty': 1.8,
                'product_uom_id': cls.meter.id})]})
        cls.wh = cls.env['stock.warehouse'].create({
            'name': 'WH T93U', 'code': 'T93U', 'manufacture_steps': 'pbm'})
        cls.stock = cls.wh.lot_stock_id
        cls.pbm = cls.wh.pbm_loc_id
        cls.pbm.location_id = cls.stock
        cls.rack = cls.env['stock.location'].create({
            'name': 'Рафт T93U', 'usage': 'internal',
            'location_id': cls.stock.id})
        cls.wh.manu_type_id.staged_preparation_enabled = True
        cls.lot_bar = cls.env['stock.lot'].create({
            'name': 'T93U-6500', 'product_id': cls.bar.id,
            'company_id': company.id, 'bar_length_mm': 6500.0})
        cls.supplier = cls.env.ref('stock.stock_location_suppliers')
        cls.wc = cls.env['mrp.workcenter'].create({'name': 'T93U cut'})

    # ── помощници ──────────────────────────────────────────────────────
    def _receive(self, qty):
        move = self.env['stock.move'].create({
            'name': 'T93U receipt', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': qty,
            'price_unit': 2.0, 'location_id': self.supplier.id,
            'location_dest_id': self.rack.id})
        move._action_confirm()
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id, 'product_id': self.bar.id,
            'product_uom_id': self.meter.id, 'location_id': self.supplier.id,
            'location_dest_id': self.rack.id, 'lot_id': self.lot_bar.id,
            'quantity': qty, 'picked': True})
        move.picked = True
        move._action_done()

    def _mo(self):
        mo = self.env['mrp.production'].create({
            'product_id': self.window.id, 'product_qty': 1.0,
            'bom_id': self.bom.id, 'picking_type_id': self.wh.manu_type_id.id})
        mo.action_confirm()
        return mo

    def _prepared(self):
        """Две МО, ЕДИН разкрой (по един прът 6500 на МО), партиден PfP."""
        self._receive(13.0)
        mos = self._mo() | self._mo()
        opt = self.env['mrp.cutting.optimization'].create({
            'name': 'T93U', 'material_domain': 'mrp_production',
            'min_offcut_length': 500.0})
        pattern = self.env['mrp.cutting.pattern'].create({
            'optimization_id': opt.id, 'name': 'T93U — P1', 'usage_count': 2,
            'bar_capacity_mm': 6500.0, 'cuts_json': '{"1800.00": 1}',
            'bar_product_id': self.bar.id, 'source_model': 'stock.lot',
            'source_id': self.lot_bar.id})
        Bar = self.env['mrp.cutting.bar']
        for i, mo in enumerate(mos, start=1):
            Bar.create({
                'pattern_id': pattern.id, 'bar_index': i, 'capacity_mm': 6500.0,
                'remnant_mm': 4638.0, 'disposition': 'offcut',
                'line_ids': [(0, 0, {'length_mm': 1800.0,
                                     'production_id': mo.id})]})
        opt.write({'state': 'done', 'offcut_birth_mode': 'transfer',
                   'production_ids': [(6, 0, mos.ids)]})
        mos.staged_cutting_optimization_id = opt
        mos.move_raw_ids.forced_lot_ids = self.lot_bar
        opt._build_cut_allocations()
        mos.state = 'preparation'
        with patch.object(type(mos), '_staged_trolleys_and_export',
                          return_value=True):
            mos._staged_do_prepare()
        return mos, opt

    def _pc(self, mos):
        return mos._staged_prep_pickings()

    def _allocations(self, mos):
        return self.env['mrp.cutting.allocation'].search([
            ('production_id', 'in', mos.ids)])

    # ① ─────────────────────────────────────────────────────────────────
    def test_the_batch_shares_one_pc(self):
        mos, _opt = self._prepared()
        self.assertEqual(len(self._pc(mos)), 1,
                         "двете МО не споделят PC — сценарият не е партидата")

    def test_undo_of_the_batch_deletes_the_pc(self):
        mos, _opt = self._prepared()
        pc = self._pc(mos)
        moves = pc.move_ids
        mos.action_unprepare_production(target_state='confirmed')
        self.assertFalse(pc.exists(),
                         "PC-то остана — новото Prepare ще се слее в него (×2)")
        self.assertTrue(all(m.state == 'cancel' for m in moves.exists()))
        for mo in mos:
            live = mo.move_raw_ids.filtered(
                lambda m: m.product_id == self.bar and m.state != 'cancel')
            self.assertTrue(live, "поръчката остана без суров ред за пръта")
            self.assertEqual(live.location_id, self.stock,
                             "консумацията не е върната на една стъпка")
            self.assertFalse(live.staged_pick_move_id)
            self.assertFalse(mo.staged_released)

    # ② ─────────────────────────────────────────────────────────────────
    def test_undo_of_one_order_names_the_other(self):
        mos, _opt = self._prepared()
        pc = self._pc(mos)
        first, second = mos[0], mos[1]
        with self.assertRaises(UserError) as cm:
            first.action_unprepare_production(target_state='confirmed')
        self.assertIn(second.name, str(cm.exception))
        self.assertTrue(pc.exists())
        self.assertTrue(first.staged_released, "отказът все пак пипна поръчката")

    # ③ ─────────────────────────────────────────────────────────────────
    def test_undo_releases_the_cutting_run(self):
        mos, _opt = self._prepared()
        self.assertTrue(self._allocations(mos))
        mos.action_unprepare_production(target_state='confirmed')
        self.assertFalse(self._allocations(mos),
                         "разпределенията на стария разкрой останаха — ×2")
        self.assertFalse(mos.staged_cutting_optimization_id)

    # ④ ─────────────────────────────────────────────────────────────────
    def test_a_planned_order_goes_back_to_preparation(self):
        mos, _opt = self._prepared()
        planned = mos[0]
        start = fields.Datetime.now()
        self.env['mrp.workorder'].create({
            'name': 'T93U cut', 'production_id': planned.id,
            'workcenter_id': self.wc.id,
            'product_uom_id': planned.product_uom_id.id,
            'date_start': start, 'date_finished': start + timedelta(hours=1)})
        self.assertTrue(planned.is_planned)
        self.assertFalse(mos[1].is_planned)
        mos.action_unprepare_production(target_state='confirmed')
        self.assertEqual(planned.state, 'preparation',
                         "планирано МО без Plan и без Prepare — няма изход")
        self.assertEqual(mos[1].state, 'confirmed')

    # ⑤ ─────────────────────────────────────────────────────────────────
    def test_the_wizard_counts_the_pc(self):
        mos, _opt = self._prepared()
        wizard = self.env['mrp.production.unprepare.wizard'].create({
            'production_ids': [(6, 0, mos.ids)]})
        self.assertEqual(wizard.picking_count, 1,
                         "визардът казва „0 трансфера“ при жив PC")
