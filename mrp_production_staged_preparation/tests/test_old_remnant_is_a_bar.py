# -*- coding: utf-8 -*-
"""Прът от стар остатък е като цял прът (№93, Любо ТГ 167875/167877).

Сценарият, през истинския PfP (`_staged_do_prepare`), два FIFO слоя:
```
приход  „4640" 4,64 м × 3,00 в Remnant/Offcut   (по-старият слой)
приход  „6500" 6,50 м × 2,00 на Рафта
разкрой прът 6500: парче 1,80 → остатък 4638 мм → „4630" (4,63, надолу)
        стар остатък 4640: парче 2,90 → остатък „1640" (1,64)
```
  ① PC е ЕДИН пикинг с два източника: „6500" 6,50 от Рафта и „4640" 4,64
    от Remnant/Offcut — нито ред от буфера; крак Offcut → Production няма;
  ② трансферът „Remnants" чака: „4630" (от 6500) и „1640" (от 4640);
  ③ PC валидиран ⇒ смени В БУФЕРА 6500 → 4630 и 4640 → 1640, равна
    стойност (13,89 и 3,29 — през двата слоя); трансферът „Готов";
  ④ МО-то изписва от буфера 1,87 от „6500" и 4,64 − 1,64 = 3,00 от „4640";
  ⑤ след Produce и трансфера в буфера не остава нищо ничие;
  ⑥ PC не взема от буфера (дестинацията), дори там да лежи същият лот.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOldRemnantIsABar(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang='en_US'))
        company = cls.env.company
        Account = cls.env['account.account']

        def acc(code, name):
            return Account.create({'code': code, 'name': name,
                                   'account_type': 'asset_current'})
        cls.acc_in = acc('T93BIN', 'T93B stock input')
        cls.acc_out = acc('T93BOUT', 'T93B stock output')
        cls.acc_val = acc('T93BVAL', 'T93B stock valuation')
        journal = cls.env['account.journal'].create({
            'name': 'T93B stock', 'code': 'T93BJ', 'type': 'general'})
        categ = cls.env['product.category'].create({
            'name': 'T93B bars', 'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
            'property_stock_account_input_categ_id': cls.acc_in.id,
            'property_stock_account_output_categ_id': cls.acc_out.id,
            'property_stock_valuation_account_id': cls.acc_val.id,
            'property_stock_journal': journal.id,
        })
        cls.relabel_loc = company._get_lot_relabel_location()
        cls.relabel_loc.write({
            'valuation_in_account_id': acc('T93BLIN', 'T93B rel in').id,
            'valuation_out_account_id': acc('T93BLOUT', 'T93B rel out').id,
        })
        cls.meter = cls.env.ref('uom.product_uom_meter')
        cls.bar = cls.env['product.product'].create({
            'name': 'PVC frame T93B', 'is_storable': True, 'tracking': 'lot',
            'categ_id': categ.id,
            'uom_id': cls.meter.id, 'uom_po_id': cls.meter.id})
        cls.window = cls.env['product.product'].create({
            'name': 'Window T93B', 'is_storable': True})
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.window.product_tmpl_id.id,
            'product_qty': 1.0, 'consumption': 'flexible',
            'bom_line_ids': [(0, 0, {
                'product_id': cls.bar.id, 'product_qty': 1.8,
                'product_uom_id': cls.meter.id})]})
        # №107: свой склад на две стъпки — чуждият не се пипа.
        cls.wh = cls.env['stock.warehouse'].create({
            'name': 'WH T93B', 'code': 'T93B', 'manufacture_steps': 'pbm'})
        cls.stock = cls.wh.lot_stock_id
        cls.pbm = cls.wh.pbm_loc_id
        # Като на живо: WH/Stock/Pre-Production; Remnant/Offcut — под
        # WH/Stock, до буфера (ADR-0051); целите пръти — на Рафта.
        cls.pbm.location_id = cls.stock
        cls.off = cls.env.ref(
            'cutting_plugin_mrp_production.stock_location_offcut')
        cls.off.location_id = cls.stock
        cls.rack = cls.env['stock.location'].create({
            'name': 'Рафт T93B', 'usage': 'internal',
            'location_id': cls.stock.id})
        cls.wh.manu_type_id.staged_preparation_enabled = True
        Lot = cls.env['stock.lot']
        cls.lot_bar = Lot.create({
            'name': 'T93B-6500', 'product_id': cls.bar.id,
            'company_id': company.id, 'bar_length_mm': 6500.0})
        cls.lot_old = Lot.create({
            'name': 'T93B-4640', 'product_id': cls.bar.id,
            'company_id': company.id, 'is_offcut': True,
            'offcut_length_mm': 4640.0})
        cls.supplier = cls.env.ref('stock.stock_location_suppliers')

    # ── помощници ──────────────────────────────────────────────────────
    def _receive(self, location, lot, qty, price):
        move = self.env['stock.move'].create({
            'name': 'T93B receipt', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': qty,
            'price_unit': price, 'location_id': self.supplier.id,
            'location_dest_id': location.id})
        move._action_confirm()
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id, 'product_id': self.bar.id,
            'product_uom_id': self.meter.id, 'location_id': self.supplier.id,
            'location_dest_id': location.id, 'lot_id': lot.id,
            'quantity': qty, 'picked': True})
        move.picked = True
        move._action_done()

    def _qty(self, location, lot):
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', self.bar.id), ('lot_id', '=', lot.id),
            ('location_id', '=', location.id)]).mapped('quantity'))

    def _lines(self, moves):
        """{(локация, лот): количество} на резервацията."""
        out = {}
        for ml in moves.move_line_ids:
            key = (ml.location_id, ml.lot_id)
            out[key] = round(out.get(key, 0.0) + ml.quantity, 6)
        return out

    def _relabels(self, lot_src):
        return self.env['stock.move'].search([
            ('lot_relabel_role', '!=', False),
            ('lot_relabel_src_lot_id', '=', lot_src.id)], order='id')

    def _done(self, picking):
        picking.move_ids.picked = True
        picking._action_done()

    def _prepared(self):
        """Два слоя, МО, разкрой, PfP. Връща (mo, opt)."""
        self._receive(self.off, self.lot_old, 4.64, 3.0)    # по-старият слой
        self._receive(self.rack, self.lot_bar, 6.5, 2.0)
        mo = self.env['mrp.production'].create({
            'product_id': self.window.id, 'product_qty': 1.0,
            'bom_id': self.bom.id, 'picking_type_id': self.wh.manu_type_id.id})
        mo.action_confirm()
        opt = self.env['mrp.cutting.optimization'].create({
            'name': 'T93B', 'material_domain': 'mrp_production',
            'min_offcut_length': 500.0})
        fresh = self.env['mrp.cutting.pattern'].create({
            'optimization_id': opt.id, 'name': 'T93B — P1', 'usage_count': 1,
            'bar_capacity_mm': 6500.0, 'cuts_json': '{"1800.00": 1}',
            'bar_product_id': self.bar.id, 'source_model': 'stock.lot',
            'source_id': self.lot_bar.id})
        old = self.env['mrp.cutting.pattern'].create({
            'optimization_id': opt.id, 'name': 'T93B — P2', 'usage_count': 1,
            'bar_capacity_mm': 4640.0, 'cuts_json': '{"2900.00": 1}',
            'bar_product_id': self.bar.id, 'source_model': 'stock.lot',
            'source_id': self.lot_old.id,
            'source_offcut_lot_id': self.lot_old.id})
        Bar = self.env['mrp.cutting.bar']
        Bar.create({
            'pattern_id': fresh.id, 'bar_index': 1, 'capacity_mm': 6500.0,
            'remnant_mm': 4638.0, 'disposition': 'offcut',
            'line_ids': [(0, 0, {'length_mm': 1800.0,
                                 'production_id': mo.id})]})
        Bar.create({
            'pattern_id': old.id, 'bar_index': 1, 'capacity_mm': 4640.0,
            'remnant_mm': 1640.0, 'disposition': 'offcut', 'is_leftover': True,
            'line_ids': [(0, 0, {'length_mm': 2900.0,
                                 'production_id': mo.id})]})
        opt.write({'state': 'done', 'offcut_birth_mode': 'transfer',
                   'production_ids': [(6, 0, mo.ids)]})
        mo.staged_cutting_optimization_id = opt
        # Пинът на `_staged_optimize_and_gate` (generate_piece_lots): целият
        # прът на суровото движение.
        mo.move_raw_ids.forced_lot_ids = self.lot_bar
        opt._build_cut_allocations()
        mo.state = 'preparation'
        with patch.object(type(mo), '_staged_trolleys_and_export',
                          return_value=True):
            mo._staged_do_prepare()
        return mo, opt

    def _pc(self, opt):
        return self.env['stock.picking'].search([
            ('cutting_optimization_id', '=', opt.id),
            ('location_dest_id', '=', self.pbm.id)])

    def _remnants(self, opt):
        return self.env['stock.move'].search([
            ('staged_remnant_lot_id', '!=', False),
            ('picking_id.cutting_optimization_id', '=', opt.id)])

    # ① ② ─────────────────────────────────────────────────────────────
    def test_one_pc_carries_the_bar_and_the_old_remnant(self):
        mo, opt = self._prepared()
        self.assertTrue(mo.staged_released)
        pc = self._pc(opt)
        self.assertEqual(len(pc), 1, "старият остатък не е в PC на целите")
        self.assertEqual(pc.picking_type_id, self.wh.pbm_type_id)
        self.assertEqual(pc.location_id, self.stock)
        self.assertEqual(self._lines(pc.move_ids), {
            (self.rack, self.lot_bar): 6.5,
            (self.off, self.lot_old): 4.64,
        }, "PC не е заковал лота и подлокацията")
        old_pick = pc.move_ids.filtered('staged_offcut_src_lot_id')
        self.assertEqual(old_pick.staged_offcut_src_lot_id, self.lot_old)
        self.assertEqual(old_pick.staged_offcut_production_id, mo)
        # Крак Offcut → Production — няма; консумацията е само от буфера.
        cons = mo.move_raw_ids.filtered(
            lambda m: m.product_id == self.bar and m.state != 'cancel')
        self.assertEqual(cons.location_id, self.pbm, "крак покрай буфера")
        self.assertAlmostEqual(sum(cons.mapped('product_uom_qty')), 4.87, 2,
                               msg="МО не изписва пръти − остатъци")
        # ② Трансферът на остатъците чака, нищо не е сменено.
        rem = self._remnants(opt)
        self.assertEqual(
            {(m.staged_remnant_src_lot_id, m.staged_remnant_lot_id.name,
              round(m.product_uom_qty, 2)) for m in rem},
            {(self.lot_bar, '4630', 4.63), (self.lot_old, '1640', 1.64)})
        self.assertEqual(rem.picking_id.state, 'confirmed')
        self.assertEqual(rem.location_id, self.pbm)
        self.assertEqual(rem.location_dest_id, self.off)
        self.assertFalse(self._relabels(self.lot_old))
        self.assertAlmostEqual(self._qty(self.off, self.lot_old), 4.64, 2)

    # ③ ④ ⑤ ─────────────────────────────────────────────────────────────
    def test_the_old_remnant_is_relabelled_in_the_buffer_and_consumed(self):
        mo, opt = self._prepared()
        pc = self._pc(opt)
        rem = self._remnants(opt)

        self._done(pc)

        # ③ смените — в буфера, равна стойност, през двата слоя
        values = {}
        for src in (self.lot_bar, self.lot_old):
            pair = self._relabels(src)
            self.assertEqual(len(pair), 2, "лотът на %s не е сменен" % src.name)
            out = pair.filtered(lambda m: m.lot_relabel_role == 'out')
            inn = out.lot_relabel_pair_id
            self.assertEqual(out.location_id, self.pbm,
                             "смяната не е в буфера")
            self.assertEqual(inn.location_dest_id, self.pbm)
            v_out = -sum(out.stock_valuation_layer_ids.mapped('value'))
            v_in = sum(inn.stock_valuation_layer_ids.mapped('value'))
            self.assertAlmostEqual(v_in, v_out, places=2, msg="„+“ ≠ „−“")
            values[src] = round(v_in, 2)
        # 4,63 от по-стария слой (× 3,00) = 13,89; 1,64 = 0,01 × 3,00 +
        # 1,63 × 2,00 = 3,29.
        self.assertEqual(values, {self.lot_bar: 13.89, self.lot_old: 3.29})
        self.assertEqual(rem.picking_id.state, 'assigned')
        self.assertEqual(self._lines(rem), {
            (self.pbm, rem.filtered(
                lambda m: m.staged_remnant_src_lot_id == self.lot_bar
            ).staged_remnant_lot_id): 4.63,
            (self.pbm, rem.filtered(
                lambda m: m.staged_remnant_src_lot_id == self.lot_old
            ).staged_remnant_lot_id): 1.64,
        })
        # ④ МО-то: от буфера, нето от новите остатъци
        cons = mo.move_raw_ids.filtered(
            lambda m: m.product_id == self.bar and m.state != 'cancel')
        self.assertEqual(self._lines(cons), {
            (self.pbm, self.lot_bar): 1.87,
            (self.pbm, self.lot_old): 3.0,
        })
        mo.qty_producing = 1.0
        mo.move_raw_ids.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, 'done')
        consumed = -sum(cons.stock_valuation_layer_ids.mapped('value'))
        self.assertAlmostEqual(consumed, 9.74, places=2)   # 4,87 × 2,00
        self._done(rem.picking_id)
        # ⑤ в буфера — нищо ничие
        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.bar.id),
            ('location_id', 'child_of', self.pbm.id)])
        self.assertFalse(quants.filtered(lambda q: round(q.quantity, 6)),
                         "в буфера остана: %s" % [
                             (q.lot_id.name, q.quantity) for q in quants
                             if round(q.quantity, 6)])
        lot_1640 = rem.staged_remnant_lot_id.filtered(
            lambda l: l.name == '1640')
        lot_4630 = rem.staged_remnant_lot_id - lot_1640
        self.assertAlmostEqual(self._qty(self.off, lot_1640), 1.64, 2)
        self.assertAlmostEqual(self._qty(self.off, lot_4630), 4.63, 2)
        self.assertAlmostEqual(self._qty(self.off, self.lot_old), 0.0, 2)
        # Стойността не се губи: 13,92 + 13,00 = 9,74 изписано + 17,18 на
        # рафта с остатъците.
        remaining = sum(self.env['stock.valuation.layer'].search([
            ('product_id', '=', self.bar.id)]).mapped('remaining_value'))
        self.assertAlmostEqual(remaining, 17.18, places=2)

    def test_one_pc_when_the_remnants_lie_beside_its_source(self):
        """Като на fulltest: PC тръгва от „Рафт" (`lot_stock_id` = 246), а
        Remnant/Offcut е до него, под общия WH/Stock (ADR-0051). Пак ЕДИН
        пикинг: редът на стария остатък тръгва от самата остатъчна локация."""
        common = self.env['stock.location'].create({
            'name': 'WH-Stock T93B', 'usage': 'internal',
            'location_id': self.wh.view_location_id.id})
        self.off.location_id = common
        mo, opt = self._prepared()
        pc = self._pc(opt)
        self.assertEqual(len(pc), 1)
        old_pick = pc.move_ids.filtered('staged_offcut_src_lot_id')
        self.assertEqual(old_pick.location_id, self.off)
        self.assertEqual(self._lines(pc.move_ids), {
            (self.rack, self.lot_bar): 6.5,
            (self.off, self.lot_old): 4.64,
        })
        self._done(pc)
        cons = mo.move_raw_ids.filtered(
            lambda m: m.product_id == self.bar and m.state != 'cancel')
        self.assertEqual(self._lines(cons), {
            (self.pbm, self.lot_bar): 1.87,
            (self.pbm, self.lot_old): 3.0,
        })

    def test_undo_cancels_the_old_remnant_in_the_pc(self):
        mo, opt = self._prepared()
        pc = self._pc(opt)
        old_pick = pc.move_ids.filtered('staged_offcut_src_lot_id')
        mo.action_unprepare_production(target_state='confirmed')
        self.assertEqual(old_pick.state, 'cancel')
        self.assertFalse(old_pick.move_line_ids)

    # ⑥ ─────────────────────────────────────────────────────────────────
    def test_the_pc_never_reserves_from_the_buffer(self):
        """Същият лот лежи и в буфера (по-стар) — PC взема само от Рафта."""
        self._receive(self.pbm, self.lot_bar, 6.5, 2.0)
        self._receive(self.rack, self.lot_bar, 6.5, 2.0)
        pick = self.env['stock.move'].create({
            'name': 'T93B PC', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': 6.5,
            'location_id': self.stock.id, 'location_dest_id': self.pbm.id,
            'picking_type_id': self.wh.pbm_type_id.id,
            'forced_lot_ids': [(6, 0, self.lot_bar.ids)]})
        cons = self.env['stock.move'].create({
            'name': 'T93B N', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': 6.5,
            'location_id': self.pbm.id,
            'location_dest_id': self.bar.property_stock_production.id,
            'staged_pick_move_id': pick.id})
        pick._action_confirm(merge=False)
        self.assertTrue(pick.staged_consumption_ids)
        pick._do_unreserve()
        pick._action_assign()
        self.assertEqual(self._lines(pick), {(self.rack, self.lot_bar): 6.5},
                         "PC взе от буфера — от собствената си дестинация")
        self.assertTrue(cons)

    def test_the_old_remnant_is_taken_only_from_the_remnant_location(self):
        """„4640" лежи и на Рафта (по-стар) — редът на стария остатък в PC
        взема САМО от Remnant/Offcut."""
        self._receive(self.rack, self.lot_old, 4.64, 3.0)
        self._receive(self.off, self.lot_old, 4.64, 3.0)
        pick = self.env['stock.move'].create({
            'name': 'T93B old', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': 4.64,
            'location_id': self.stock.id, 'location_dest_id': self.pbm.id,
            'picking_type_id': self.wh.pbm_type_id.id,
            'forced_lot_ids': [(6, 0, self.lot_old.ids)],
            'staged_offcut_src_lot_id': self.lot_old.id})
        pick._action_confirm(merge=False)
        pick._do_unreserve()
        pick._action_assign()
        self.assertEqual(self._lines(pick), {(self.off, self.lot_old): 4.64})

    def test_the_old_remnant_landing_alone_wakes_the_consumption(self):
        """Старият остатък кацна сам (целият прът — в backorder): МО-то
        запазва 3,00 от „4640" веднага, а смяната на лота чака целия PC."""
        mo, opt = self._prepared()
        pc = self._pc(opt)
        old_pick = pc.move_ids.filtered('staged_offcut_src_lot_id')
        old_pick.picked = True
        pc._action_done()
        self.assertEqual(old_pick.state, 'done')
        self.assertTrue(pc.backorder_ids, "постановката: няма backorder")
        cons = mo.move_raw_ids.filtered(
            lambda m: m.product_id == self.bar and m.state != 'cancel')
        self.assertEqual(self._lines(cons), {(self.pbm, self.lot_old): 3.0},
                         "консумацията не чу стария остатък")
        self.assertFalse(self._relabels(self.lot_old),
                         "смяната не дочака целия PC")
