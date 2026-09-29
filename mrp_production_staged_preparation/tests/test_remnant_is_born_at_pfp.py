# -*- coding: utf-8 -*-
"""Остатъкът се ражда при PfP, лотът му се сменя при кацането (№93, 29.09).

Решение на Любо (ТГ 167821/167822/167824/167825) и на Росен (29.09, „вариант А
— логиката е като инвентаризация"):
  ① PfP ражда ЕДИН трансфер „Remnants <разкрой>" за целия разкрой:
    Pre-Production → Remnant/Offcut, по едно движение на остатък, количество =
    `offcut_new` на плъгина, лот = дължината („4630"). Чака.
  ② PC валидиран, прътите кацнаха ⇒ в буфера 6500 → 4630 през „Lot Relabel"
    (две движения, една референция, равна стойност, настроените сметки), и
    трансферът резервира ТОЧНО 4630 ⇒ „Готов".
  ③ частичен PC ⇒ смяната чака backorder-а (целия PC).
  ④ „Produce" не ражда нищо.
  ⑤ Undo Preparation отказва трансфера и връща лота (4630 → 6500), пак със
    следа и равна стойност.
  ⑥ прът от стар остатък: лотът се сменя НА МЯСТО, в Remnant/Offcut, още при
    PfP — движение в трансфера за него няма.
  ⑦ липсващи сметки ⇒ валидирането на PC пада с ясна грешка;
    не стига прът ⇒ бележка на разкроя, другите остатъци продължават.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRemnantIsBornAtPfp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang='en_US'))
        company = cls.env.company
        Account = cls.env['account.account']

        def acc(code, name):
            return Account.create({'code': code, 'name': name,
                                   'account_type': 'asset_current'})
        cls.acc_in = acc('T93PIN', 'T93P stock input')
        cls.acc_out = acc('T93POUT', 'T93P stock output')
        cls.acc_val = acc('T93PVAL', 'T93P stock valuation')
        cls.acc_rel_in = acc('T93PLIN', 'T93P relabel incoming')
        cls.acc_rel_out = acc('T93PLOUT', 'T93P relabel outgoing')
        journal = cls.env['account.journal'].create({
            'name': 'T93P stock', 'code': 'T93PJ', 'type': 'general'})
        categ = cls.env['product.category'].create({
            'name': 'T93P bars', 'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
            'property_stock_account_input_categ_id': cls.acc_in.id,
            'property_stock_account_output_categ_id': cls.acc_out.id,
            'property_stock_valuation_account_id': cls.acc_val.id,
            'property_stock_journal': journal.id,
        })
        cls.relabel_loc = company._get_lot_relabel_location()
        cls.relabel_loc.write({
            'valuation_in_account_id': cls.acc_rel_in.id,
            'valuation_out_account_id': cls.acc_rel_out.id,
        })
        cls.meter = cls.env.ref('uom.product_uom_meter')
        cls.bar = cls.env['product.product'].create({
            'name': 'PVC frame T93P', 'is_storable': True, 'tracking': 'lot',
            'categ_id': categ.id,
            'uom_id': cls.meter.id, 'uom_po_id': cls.meter.id})
        cls.window = cls.env['product.product'].create({
            'name': 'Window T93P', 'is_storable': True})
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.window.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.bar.id, 'product_qty': 1.8,
                'product_uom_id': cls.meter.id})]})
        cls.wh = cls.env['stock.warehouse'].search(
            [('company_id', '=', company.id)], limit=1)
        Loc = cls.env['stock.location']
        cls.rack = Loc.create({'name': 'Рафт T93P', 'usage': 'internal',
                               'location_id': cls.wh.lot_stock_id.id})
        cls.buf = Loc.create({'name': 'Pre-Production T93P',
                              'usage': 'internal',
                              'location_id': cls.wh.lot_stock_id.id})
        # Като на живо: остатъчната локация е ДЕТЕ на буфера.
        cls.off = cls.env.ref(
            'cutting_plugin_mrp_production.stock_location_offcut')
        cls.off.location_id = cls.buf
        cls.lot_bar = cls.env['stock.lot'].create({
            'name': 'T93P-6500', 'product_id': cls.bar.id,
            'company_id': company.id})
        cls.supplier = cls.env.ref('stock.stock_location_suppliers')

    # ── помощници ──────────────────────────────────────────────────────
    def _stock(self, location, qty, lot=None, price=2.0):
        """Приход от доставчик — със стойност, за да има какво да се мери."""
        move = self.env['stock.move'].create({
            'name': 'T93P receipt', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': qty,
            'price_unit': price, 'location_id': self.supplier.id,
            'location_dest_id': location.id})
        move._action_confirm()
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id, 'product_id': self.bar.id,
            'product_uom_id': self.meter.id, 'location_id': self.supplier.id,
            'location_dest_id': location.id,
            'lot_id': (lot or self.lot_bar).id, 'quantity': qty,
            'picked': True})
        move.picked = True
        move._action_done()

    def _qty(self, location, lot):
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', self.bar.id), ('lot_id', '=', lot.id),
            ('location_id', '=', location.id)]).mapped('quantity'))

    def _mo(self):
        mo = self.env['mrp.production'].create({
            'product_id': self.window.id, 'product_qty': 1.0,
            'bom_id': self.bom.id, 'location_src_id': self.buf.id})
        mo.action_confirm()
        # Консумацията тръгва от БУФЕРА, като след PfP. На жива база типът
        # производство налага своята локация (fulltest: WH/Stock/Рафт) и
        # движението резервира пръта още от рафта — тогава PC не може да го
        # вземе целия и остава backorder (№93, мерено на teo-fulltest-t93v2).
        raw = mo.move_raw_ids
        raw._do_unreserve()
        raw.write({'location_id': self.buf.id})
        return mo

    def _run(self, mos, bars, mode='transfer', name='T93P'):
        """bars = [(remnant_mm, disposition, [(mo, length), ...]), ...]"""
        opt = self.env['mrp.cutting.optimization'].create({
            'name': name, 'material_domain': 'mrp_production',
            'min_offcut_length': 500.0})
        pattern = self.env['mrp.cutting.pattern'].create({
            'optimization_id': opt.id, 'name': '%s — P53' % name,
            'usage_count': len(bars), 'bar_capacity_mm': 6500.0,
            'cuts_json': '{}', 'bar_product_id': self.bar.id,
            'source_model': 'stock.lot', 'source_id': self.lot_bar.id,
        })
        for i, (rem, disp, cuts) in enumerate(bars, 1):
            self.env['mrp.cutting.bar'].create({
                'pattern_id': pattern.id, 'bar_index': i, 'capacity_mm': 6500.0,
                'remnant_mm': rem, 'disposition': disp,
                'line_ids': [(0, 0, {'length_mm': ln, 'production_id': m.id})
                             for m, ln in cuts],
            })
        opt.offcut_birth_mode = mode
        opt.state = 'done'
        opt.production_ids = [(6, 0, mos.ids)]
        mos.staged_cutting_optimization_id = opt
        return opt

    def _pc(self, mos, qty):
        """PC на партидата: Рафт → буфера, със следата към консумациите."""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.wh.int_type_id.id,
            'location_id': self.rack.id, 'location_dest_id': self.buf.id})
        pick = self.env['stock.move'].create({
            'name': 'T93P PC', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': qty,
            'location_id': self.rack.id, 'location_dest_id': self.buf.id,
            'picking_id': picking.id})
        picking.action_confirm()
        picking.action_assign()
        mos.move_raw_ids.filtered(
            lambda m: m.product_id == self.bar).staged_pick_move_id = pick
        return picking

    def _validate(self, picking, qty=None):
        line = picking.move_ids.move_line_ids
        if qty is not None:
            line.quantity = qty
        picking.move_ids.picked = True
        picking._action_done()

    def _two(self):
        """Два МО, по един остатък: 4638 → „4630" (4,63), 4250 → „4250"."""
        self._stock(self.rack, 13.0)
        mo1, mo2 = self._mo(), self._mo()
        opt = self._run(mo1 | mo2, [(4638.0, 'offcut', [(mo1, 1800.0)]),
                                    (4250.0, 'offcut', [(mo2, 2200.0)])])
        opt._build_cut_allocations()
        pc = self._pc(mo1 | mo2, 13.0)
        return mo1, mo2, opt, pc

    def _remnant_moves(self, opt):
        return self.env['stock.move'].search([
            ('staged_remnant_lot_id', '!=', False),
            ('picking_id.cutting_optimization_id', '=', opt.id)])

    def _relabels(self, lot_src=None):
        dom = [('lot_relabel_role', '!=', False),
               ('product_id', '=', self.bar.id)]
        if lot_src:
            dom.append(('lot_relabel_src_lot_id', '=', lot_src.id))
        return self.env['stock.move'].search(dom, order='id')

    # ① ─────────────────────────────────────────────────────────────────
    def test_pfp_births_one_waiting_transfer_for_the_run(self):
        mo1, mo2, opt, pc = self._two()
        new_off = opt.allocation_ids.filtered(lambda a: a.kind == 'offcut_new')
        self.assertAlmostEqual(sum(new_off.mapped('quantity')), 8.88, places=2,
                               msg="постановката: плъгинът не вади остатъка")

        moves = (mo1 | mo2)._staged_birth_remnants_at_pfp()

        self.assertEqual(len(moves), 2, "по едно движение на остатък")
        self.assertEqual(len(moves.picking_id), 1, "един трансфер на разкроя")
        picking = moves.picking_id
        self.assertEqual(picking.cutting_optimization_id, opt)
        self.assertEqual(picking.picking_type_id.code, 'internal')
        self.assertEqual(picking.origin, 'Remnants T93P')
        self.assertEqual(moves.location_id, self.buf)
        self.assertEqual(moves.location_dest_id, self.off)
        self.assertEqual(sorted(moves.mapped('staged_remnant_lot_id.name')),
                         ['4250', '4630'])
        self.assertEqual(moves.staged_remnant_src_lot_id, self.lot_bar)
        self.assertTrue(all(moves.staged_remnant_lot_id.mapped('is_offcut')))
        by_lot = {m.staged_remnant_lot_id.name: m.product_uom_qty
                  for m in moves}
        self.assertAlmostEqual(by_lot['4630'], 4.63, places=2)
        self.assertAlmostEqual(by_lot['4250'], 4.25, places=2)
        self.assertAlmostEqual(sum(moves.mapped('product_uom_qty')),
                               sum(new_off.mapped('quantity')), places=2,
                               msg="друго число от това, което плъгинът вади")
        # Чака: прътите са на рафта, лотът не е сменен, нищо не е запазено.
        self.assertEqual(picking.state, 'confirmed')
        self.assertFalse(moves.move_line_ids)
        self.assertFalse(self._relabels())
        self.assertAlmostEqual(self._qty(self.rack, self.lot_bar), 13.0, 2)

    def test_a_second_pfp_does_not_birth_twice(self):
        mo1, mo2, opt, pc = self._two()
        first = (mo1 | mo2)._staged_birth_remnants_at_pfp()
        again = (mo1 | mo2)._staged_birth_remnants_at_pfp()
        self.assertEqual(len(first), 2)
        self.assertFalse(again, "повторна подготовка роди втори остатък")
        self.assertEqual(len(self._remnant_moves(opt)), 2)

    def test_the_run_decides_not_the_mo(self):
        """Един МО от разкроя на партидата ражда остатъците на ЦЕЛИЯ разкрой."""
        mo1, mo2, opt, pc = self._two()
        moves = mo1._staged_birth_remnants_at_pfp()
        self.assertEqual(len(moves), 2)

    def test_another_birth_mode_is_left_alone(self):
        self._stock(self.buf, 6.5)
        mo = self._mo()
        for mode in ('byproduct', 'inventory'):
            self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])], mode=mode)
            self.assertFalse(mo._staged_birth_remnants_at_pfp(),
                             "режим %s не бива да се пипа" % mode)

    def test_prepare_is_where_the_birth_is_wired(self):
        """PfP (`_staged_do_prepare`) вика раждането; подателят — не."""
        # №107: свой склад на една стъпка — чуждата Pre-Production не се пипа.
        wh = self.env['stock.warehouse'].create({
            'name': 'WH T93P', 'code': 'T93P',
            'manufacture_steps': 'mrp_one_step'})
        mo = self.env['mrp.production'].create({
            'product_id': self.window.id, 'product_qty': 1.0,
            'bom_id': self.bom.id, 'picking_type_id': wh.manu_type_id.id,
            'location_src_id': self.buf.id})
        mo.action_confirm()
        opt = self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])])
        mo.picking_type_id.staged_preparation_enabled = True
        mo.state = 'preparation'
        mo.staged_released = False
        with patch.object(type(opt), 'action_move_remnants_to_offcut',
                          return_value=False) as podatel, \
                patch.object(type(mo), '_staged_birth_remnants_at_pfp',
                             return_value=self.env['stock.move']) as razhdane, \
                patch.object(type(mo), '_staged_trolleys_and_export',
                             return_value=True):
            mo._staged_do_prepare()
        self.assertEqual(razhdane.call_count, 1, "PfP не ражда остатъка")
        self.assertEqual(podatel.call_count, 0, "PfP вика подателя на плъгина")

    # ② ─────────────────────────────────────────────────────────────────
    def test_pc_done_relabels_in_the_buffer_and_reserves_the_remnant_lot(self):
        mo1, mo2, opt, pc = self._two()
        moves = (mo1 | mo2)._staged_birth_remnants_at_pfp()

        self._validate(pc)

        relabels = self._relabels()
        self.assertEqual(len(relabels), 4, "две смени по две движения")
        for out in relabels.filtered(lambda m: m.lot_relabel_role == 'out'):
            inn = out.lot_relabel_pair_id
            self.assertEqual((out.state, inn.state), ('done', 'done'))
            self.assertEqual(out.location_id, self.buf)
            self.assertEqual(out.location_dest_id, self.relabel_loc)
            self.assertEqual(inn.location_dest_id, self.buf)
            self.assertEqual(out.move_line_ids.lot_id, self.lot_bar)
            self.assertEqual(out.reference, inn.reference)
            self.assertEqual(
                out.reference, 'T93P · T93P — P53: T93P-6500 → %s'
                % inn.move_line_ids.lot_id.name)
            self.assertTrue(out.staged_relabel_bar_ref)
            self.assertFalse(out.is_inventory)
            v_out = sum(out.stock_valuation_layer_ids.mapped('value'))
            v_in = sum(inn.stock_valuation_layer_ids.mapped('value'))
            self.assertEqual(self.env.company.currency_id.compare_amounts(
                v_in, -v_out), 0, "„+“ и „−“ се разминават")
            aml = (out | inn).stock_valuation_layer_ids.account_move_id.line_ids
            self.assertEqual(aml.account_id,
                             self.acc_val | self.acc_rel_in | self.acc_rel_out)
        # 4,63 × 2,00 и 4,25 × 2,00
        values = sorted(sum(m.stock_valuation_layer_ids.mapped('value'))
                        for m in relabels.filtered(
                            lambda m: m.lot_relabel_role == 'in'))
        self.assertEqual([round(v, 2) for v in values], [8.5, 9.26])
        # Трансферът резервира ТОЧНО своите лотове.
        self.assertEqual(moves.picking_id.state, 'assigned')
        for move in moves:
            self.assertEqual(move.state, 'assigned')
            self.assertEqual(move.move_line_ids.lot_id,
                             move.staged_remnant_lot_id)
            self.assertEqual(move.move_line_ids.location_id, self.buf)
            self.assertAlmostEqual(move.quantity, move.product_uom_qty, 2)
        lot_4630 = moves.staged_remnant_lot_id.filtered(
            lambda l: l.name == '4630')
        self.assertAlmostEqual(self._qty(self.buf, lot_4630), 4.63, places=2)
        self.assertAlmostEqual(self._qty(self.buf, self.lot_bar), 4.12,
                               places=2)
        # Консумациите взимат своя дял − остатъка: 6,50 − 4,63 и 6,50 − 4,25.
        cons = (mo1 | mo2).move_raw_ids.filtered(
            lambda m: m.product_id == self.bar).sorted('id')
        self.assertEqual([round(q, 2) for q in cons.mapped('quantity')],
                         [1.87, 2.25])

    def test_a_partial_pc_waits_for_its_backorder(self):
        """Решението: смяната чака ЦЕЛИЯ PC. Кацнал е един прът от два."""
        mo1, mo2, opt, pc = self._two()
        moves = (mo1 | mo2)._staged_birth_remnants_at_pfp()

        self._validate(pc, qty=6.5)

        backorder = pc.backorder_ids
        self.assertEqual(len(backorder), 1, "постановката: няма backorder")
        self.assertFalse(self._relabels(), "смени лота при половин PC")
        self.assertEqual(moves.picking_id.state, 'confirmed')

        backorder.action_assign()
        self._validate(backorder)

        self.assertEqual(len(self._relabels()), 4)
        self.assertEqual(moves.picking_id.state, 'assigned')

    def test_the_remnant_does_not_reserve_before_its_relabel(self):
        """„Провери наличност" преди кацането не взима нищо — нито 6500 от
        буфера, нито чужд „4630"."""
        mo1, mo2, opt, pc = self._two()
        moves = (mo1 | mo2)._staged_birth_remnants_at_pfp()
        lot_4630 = moves.staged_remnant_lot_id.filtered(
            lambda l: l.name == '4630')
        self._stock(self.buf, 6.5)              # 6500 в буфера
        self._stock(self.buf, 4.63, lot=lot_4630)   # чужд „4630"
        moves.picking_id.action_assign()
        self.assertFalse(moves.move_line_ids)
        self.assertEqual(moves.picking_id.state, 'confirmed')

    # ④ ─────────────────────────────────────────────────────────────────
    def test_produce_births_nothing(self):
        mo1, mo2, opt, pc = self._two()
        (mo1 | mo2)._staged_birth_remnants_at_pfp()
        self._validate(pc)
        to_off = self.env['stock.move'].search_count(
            [('location_dest_id', '=', self.off.id)])
        relabels = len(self._relabels())
        self.bom.consumption = 'flexible'   # 1,87 изписано срещу 1,80 по рецепта
        mo1.qty_producing = 1.0
        mo1.move_raw_ids.picked = True
        with patch.object(type(mo1), '_staged_birth_remnants_at_pfp') as pfp:
            mo1.button_mark_done()
        self.assertEqual(mo1.state, 'done')
        self.assertEqual(pfp.call_count, 0)
        self.assertEqual(self.env['stock.move'].search_count(
            [('location_dest_id', '=', self.off.id)]), to_off,
            "„Produce“ роди остатък")
        self.assertEqual(len(self._relabels()), relabels,
                         "„Produce“ смени лот")
        cons = mo1.move_raw_ids.filtered(lambda m: m.product_id == self.bar)
        self.assertAlmostEqual(sum(cons.mapped('quantity')), 1.87, places=2)
        self.assertEqual(cons.move_line_ids.lot_id, self.lot_bar)

    # ⑤ ─────────────────────────────────────────────────────────────────
    def test_undo_cancels_the_transfer_and_reverses_the_relabel(self):
        mo1, mo2, opt, pc = self._two()
        moves = (mo1 | mo2)._staged_birth_remnants_at_pfp()
        self._validate(pc)
        before = len(self._relabels())

        (mo1 | mo2)._staged_undo_remnants()

        self.assertEqual(set(moves.mapped('state')), {'cancel'})
        self.assertEqual(moves.picking_id.state, 'cancel')
        back = self._relabels()[before:]
        self.assertEqual(len(back), 4, "две обратни смени по две движения")
        self.assertTrue(all(back.mapped('staged_relabel_undo')))
        for out in back.filtered(lambda m: m.lot_relabel_role == 'out'):
            inn = out.lot_relabel_pair_id
            self.assertEqual(inn.move_line_ids.lot_id, self.lot_bar)
            self.assertEqual(self.env.company.currency_id.compare_amounts(
                sum(inn.stock_valuation_layer_ids.mapped('value')),
                -sum(out.stock_valuation_layer_ids.mapped('value'))), 0)
        for lot in moves.staged_remnant_lot_id:
            self.assertAlmostEqual(self._qty(self.buf, lot), 0.0, places=2)
        self.assertAlmostEqual(self._qty(self.buf, self.lot_bar), 13.0, 2)
        Production = self.env['mrp.production']
        for m in moves:
            self.assertEqual(
                Production._staged_bar_relabel_net(m.staged_remnant_bar_ref), 0)

    def test_undo_before_landing_only_cancels(self):
        mo1, mo2, opt, pc = self._two()
        moves = (mo1 | mo2)._staged_birth_remnants_at_pfp()
        (mo1 | mo2)._staged_undo_remnants()
        self.assertEqual(set(moves.mapped('state')), {'cancel'})
        self.assertFalse(self._relabels())

    def test_undo_is_wired_into_unprepare(self):
        mo = self._mo()
        mo.picking_type_id.staged_preparation_enabled = True
        with patch.object(type(mo), '_staged_undo_remnants',
                          return_value=self.env['stock.move']) as undo:
            try:
                mo.action_unprepare_production(target_state='confirmed')
            except UserError:
                pass
        self.assertEqual(undo.call_count, 1)

    def test_a_validated_remnant_transfer_blocks_the_undo(self):
        mo1, mo2, opt, pc = self._two()
        moves = (mo1 | mo2)._staged_birth_remnants_at_pfp()
        self._validate(pc)
        moves.picking_id.move_ids.picked = True
        moves.picking_id._action_done()
        self.assertEqual(set(moves.mapped('state')), {'done'})
        with self.assertRaisesRegex(UserError, 'already cut'):
            (mo1 | mo2)._staged_undo_remnants()

    # ⑥ ─────────────────────────────────────────────────────────────────
    def test_a_remnant_of_an_old_offcut_is_relabelled_in_place(self):
        """Стар остатък „4640" (4,64 м) → парче 2,90 → нов остатък „1640".

        Кракът изписва 3,00 от „4640" в Remnant/Offcut; 1,64 остават там и
        лотът им се сменя НА МЯСТО още при PfP. Прътът 6500 до него ражда
        своя „4630" в трансфера на разкроя и чака PC."""
        self._stock(self.rack, 6.5)
        lot_old = self.env['stock.lot'].create({
            'name': 'T93P-OLD-4640', 'product_id': self.bar.id,
            'company_id': self.env.company.id, 'is_offcut': True,
            'offcut_length_mm': 4640.0})
        self._stock(self.off, 4.64, lot=lot_old)
        mo = self._mo()
        opt = self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])])
        pattern = self.env['mrp.cutting.pattern'].create({
            'optimization_id': opt.id, 'name': 'T93P — P54', 'usage_count': 1,
            'bar_capacity_mm': 4640.0, 'cuts_json': '{}',
            'bar_product_id': self.bar.id, 'source_model': 'stock.lot',
            'source_id': lot_old.id, 'source_offcut_lot_id': lot_old.id})
        self.env['mrp.cutting.bar'].create({
            'pattern_id': pattern.id, 'bar_index': 1, 'capacity_mm': 4640.0,
            'remnant_mm': 1640.0, 'disposition': 'offcut', 'is_leftover': True,
            'line_ids': [(0, 0, {'length_mm': 2900.0,
                                 'production_id': mo.id})]})
        main = mo.move_raw_ids.filtered(lambda m: m.product_id == self.bar)
        # огледало на `_staged_offcut_consumptions`: кракът от остатъчната
        leg = main.copy({'location_id': self.off.id, 'product_uom_qty': 4.64,
                         'raw_material_production_id': mo.id,
                         'state': 'draft'})
        leg._action_confirm(merge=False)
        opt._build_cut_allocations()
        self.assertAlmostEqual(leg.quantity, 3.00, places=2,
                               msg="постановката: кракът не е резервиран нето")
        pc = self._pc(mo, 6.5)

        moves = mo._staged_birth_remnants_at_pfp()

        self.assertEqual(len(moves), 1, "движение за стария остатък")
        self.assertEqual(moves.staged_remnant_lot_id.name, '4630')
        self.assertEqual(moves.picking_id.state, 'confirmed')
        lot_1640 = self.env['stock.lot'].search([
            ('product_id', '=', self.bar.id), ('name', '=', '1640')])
        relabels = self._relabels(lot_src=lot_old)
        self.assertEqual(len(relabels), 2, "лотът на стария остатък не е сменен")
        self.assertEqual(set(relabels.mapped('location_id')
                             | relabels.mapped('location_dest_id')),
                         {self.off, self.relabel_loc})
        self.assertAlmostEqual(self._qty(self.off, lot_1640), 1.64, places=2)
        self.assertAlmostEqual(self._qty(self.off, lot_old), 3.00, places=2)
        self.assertAlmostEqual(leg.quantity, 3.00, places=2,
                               msg="смяната открадна от крака")
        # Целият прът чака своя PC.
        self._validate(pc)
        self.assertEqual(moves.picking_id.state, 'assigned')
        self.assertEqual(len(self._relabels(lot_src=self.lot_bar)), 2)

    # ⑦ ─────────────────────────────────────────────────────────────────
    def test_missing_accounts_stop_the_landing_with_a_clear_error(self):
        mo1, mo2, opt, pc = self._two()
        (mo1 | mo2)._staged_birth_remnants_at_pfp()
        self.relabel_loc.valuation_in_account_id = False
        with self.assertRaisesRegex(UserError, 'valuation account'):
            self._validate(pc)

    def test_a_short_bar_is_said_and_the_others_go_on(self):
        """PC донесе един прът за два остатъка: първият получава лота си,
        вторият чака — и разкроят го казва."""
        mo1, mo2, opt, pc = self._two()
        moves = (mo1 | mo2)._staged_birth_remnants_at_pfp()
        pc.move_ids.product_uom_qty = 6.5
        pc.do_unreserve()
        pc.action_assign()
        broy = len(opt.message_ids)

        self._validate(pc)

        ready = moves.filtered(lambda m: m.state == 'assigned')
        self.assertEqual(ready.staged_remnant_lot_id.name, '4630')
        waiting = moves - ready
        self.assertEqual(waiting.state, 'confirmed')
        self.assertEqual(len(self._relabels()), 2)
        self.assertEqual(len(opt.message_ids), broy + 1, "отказът мълчи")
        self.assertIn('did not get their own lot', opt.message_ids[0].body)

    # плъгинът ────────────────────────────────────────────────────────────
    def test_the_plugin_does_not_birth_what_is_born_here(self):
        """🔴 Двойното раждане: бутонът „Generate Lots" на плъгина раждаше
        „NNNN-001" с трансфер от мястото на пръта. Куката му казва, че
        остатъкът се ражда тук."""
        mo = self._mo()
        opt = self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])])
        self.assertTrue(mo._cutting_remnant_born_at_produce(opt))
        self.assertTrue(opt._remnant_born_at_produce())
        with patch.object(type(opt), 'action_move_remnants_to_offcut',
                          return_value=False) as podatel:
            opt.action_generate_lots()
        self.assertEqual(podatel.call_count, 0,
                         "плъгинът роди остатък, който се ражда тук")

    def test_the_hook_is_off_for_another_mode_or_run(self):
        mo = self._mo()
        opt = self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])],
                        mode='inventory')
        self.assertFalse(mo._cutting_remnant_born_at_produce(opt))
        other = self._run(self._mo(), [(4638.0, 'offcut', [(mo, 1800.0)])])
        self.assertFalse(mo._cutting_remnant_born_at_produce(other),
                         "чужд разкрой — не е наш да го раждаме")
