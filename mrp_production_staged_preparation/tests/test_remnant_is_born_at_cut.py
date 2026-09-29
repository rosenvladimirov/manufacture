# -*- coding: utf-8 -*-
"""Остатъкът се ражда при РЯЗАНЕТО, от буфера, с лот = дължината (№93).

Мерено на fulltest, 28.09, разкрой 1141 (11 МО PVC):
```
PfP                 WH/Stock/Рафт → Pre-Production        лот 6500   вярно
STOR/00262          WH/Stock/Рафт → Remnant/Offcut        лот 6500   ГРЕШНО
                    P53: remnant 4638, offcut → каса 4,64 м; крило 4,25 м
```
(а) излизаше от рафта ПРЕДИ рязането, а прътът вече е в PfP към буфера ⇒ от
рафта на хартия излизат повече метри; (б) лотът е на цял прът ⇒ следващото МО
гребе остатъка като цял прът. Коренът: 30f02da1 (18.0.2.19.0) раждаше остатъка
при подготовката.

Тук се пази:
  ① подготовката (PfP) НЕ вика подателя на остатъци — нито трансфер от рафта;
  ② при рязането: Pre-Production → Remnant/Offcut, по едно движение на
    остатък, лот = дължината в мм, без суфикс. Дължината е тази, която
    складът държи: 4638 мм → 4,64 м → лот „4640" (ADR-0049, закръглението);
  ③ количеството е СЪЩОТО число, което плъгинът вади от консумацията;
  ④ повторно рязане не ражда втори остатък; два остатъка с една дължина — един
    лот;
  ⑤ прътът още не е в буфера ⇒ нищо не тръгва от рафта, и се казва.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRemnantIsBornAtCut(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.meter = cls.env.ref('uom.product_uom_meter')
        cls.bar = cls.env['product.product'].create({
            'name': 'PVC frame T93R', 'is_storable': True, 'tracking': 'lot',
            'uom_id': cls.meter.id, 'uom_po_id': cls.meter.id})
        cls.window = cls.env['product.product'].create({
            'name': 'Window T93R', 'is_storable': True})
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.window.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.bar.id, 'product_qty': 1.8,
                'product_uom_id': cls.meter.id})]})
        cls.wh = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        Loc = cls.env['stock.location']
        cls.rack = Loc.create({'name': 'Рафт T93R', 'usage': 'internal',
                               'location_id': cls.wh.lot_stock_id.id})
        cls.buf = Loc.create({'name': 'Pre-Production T93R',
                              'usage': 'internal',
                              'location_id': cls.wh.lot_stock_id.id})
        # Като на живо: остатъчната локация е ДЕТЕ на буфера.
        cls.off = cls.env.ref(
            'cutting_plugin_mrp_production.stock_location_offcut')
        cls.off.location_id = cls.buf
        cls.lot_bar = cls.env['stock.lot'].create({
            'name': 'T93R-6500', 'product_id': cls.bar.id,
            'company_id': cls.env.company.id})

    def _stock(self, location, qty, lot=None):
        quant = self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': self.bar.id, 'location_id': location.id,
            'lot_id': (lot or self.lot_bar).id, 'inventory_quantity': qty})
        quant.action_apply_inventory()

    def _qty(self, location, lot):
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', self.bar.id), ('lot_id', '=', lot.id),
            ('location_id', '=', location.id)]).mapped('quantity'))

    def _mo(self):
        mo = self.env['mrp.production'].create({
            'product_id': self.window.id, 'product_qty': 1.0,
            'bom_id': self.bom.id, 'location_src_id': self.buf.id})
        mo.action_confirm()
        return mo

    def _run(self, mo, bars, mode='transfer'):
        """bars = [(remnant_mm, disposition, [(mo, length), ...]), ...]"""
        opt = self.env['mrp.cutting.optimization'].create({
            'name': 'T93R', 'material_domain': 'mrp_production',
            'min_offcut_length': 500.0})
        pattern = self.env['mrp.cutting.pattern'].create({
            'optimization_id': opt.id, 'name': 'T93R — P53',
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
        mo.staged_cutting_optimization_id = opt
        return opt

    def _to_offcut(self):
        return self.env['stock.move'].search([
            ('product_id', '=', self.bar.id),
            ('location_dest_id', '=', self.off.id)])

    # ① ─────────────────────────────────────────────────────────────────
    def test_preparation_does_not_birth_the_remnant(self):
        """🔴 Коренът: PfP викаше подателя ⇒ Рафт → Remnant с лот 6500."""
        self._stock(self.rack, 6.5)
        mo = self._mo()
        opt = self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])])
        if self.wh.manufacture_steps != 'mrp_one_step':
            self.wh.manufacture_steps = 'mrp_one_step'
        mo.picking_type_id.staged_preparation_enabled = True
        mo.state = 'preparation'
        mo.staged_released = False
        Opt = type(opt)
        with patch.object(Opt, 'action_move_remnants_to_offcut',
                          create=True, return_value=False) as podatel, \
                patch.object(type(mo), '_staged_trolleys_and_export',
                             return_value=True):
            mo._staged_do_prepare()
        self.assertEqual(podatel.call_count, 0,
                         "подготовката роди остатък — PfP пак вика подателя")
        self.assertFalse(self._to_offcut(), "движение към остатъчната при PfP")
        self.assertAlmostEqual(self._qty(self.rack, self.lot_bar), 6.5, places=2)

    # ② ③ ─────────────────────────────────────────────────────────────────
    def test_the_remnant_is_born_from_the_buffer_with_its_length_lot(self):
        """Pre-Production → Remnant/Offcut, лот „4640", 4,64 м — като плъгина."""
        self._stock(self.rack, 6.5)
        self._stock(self.buf, 13.0)       # PfP е кацнал: два пръта в буфера
        mo = self._mo()
        opt = self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])])
        opt._build_cut_allocations()
        new_off = sum(opt.allocation_ids.filtered(
            lambda a: a.production_id == mo and a.kind == 'offcut_new'
        ).mapped('quantity'))
        self.assertAlmostEqual(new_off, 4.64, places=2,
                               msg="постановката: плъгинът не вади остатъка")

        moves = mo._staged_birth_remnants_at_cut()

        self.assertEqual(len(moves), 1, "по едно движение на остатък")
        self.assertEqual(moves, self._to_offcut())
        self.assertEqual(moves.location_id, self.buf,
                         "остатъкът не тръгва от буфера")
        self.assertAlmostEqual(moves.product_uom_qty, new_off, places=2,
                               msg="друго число от това, което плъгинът вади")
        lines = moves.move_line_ids
        self.assertEqual(lines.mapped('lot_id.name'), ['4640'],
                         "лотът не е дължината в мм")
        self.assertEqual(lines.location_id, self.buf)
        self.assertAlmostEqual(sum(lines.mapped('quantity')), 4.64, places=2)
        self.assertEqual(moves.picking_id.state, 'assigned')
        # Рафтът — непипнат; в буфера лотът на пръта е намалял с остатъка.
        self.assertAlmostEqual(self._qty(self.rack, self.lot_bar), 6.5, places=2)
        self.assertAlmostEqual(self._qty(self.buf, self.lot_bar), 8.36, places=2)
        self.assertAlmostEqual(self._qty(self.buf, lines.lot_id), 4.64, places=2)

    # ④ ─────────────────────────────────────────────────────────────────
    def test_a_second_cut_does_not_birth_twice(self):
        self._stock(self.buf, 6.5)
        mo = self._mo()
        opt = self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])])
        opt._build_cut_allocations()
        first = mo._staged_birth_remnants_at_cut()
        again = mo._staged_birth_remnants_at_cut()
        self.assertEqual(len(first), 1)
        self.assertFalse(again, "повторното рязане роди втори остатък")
        self.assertEqual(len(self._to_offcut()), 1)

    def test_two_remnants_of_one_length_share_one_lot(self):
        """Лотът е дължината — без „-001", „-002"."""
        self._stock(self.buf, 13.0)
        mo = self._mo()
        opt = self._run(mo, [(4250.0, 'offcut', [(mo, 2200.0)]),
                             (4250.0, 'offcut', [(mo, 2200.0)])])
        opt._build_cut_allocations()
        moves = mo._staged_birth_remnants_at_cut()
        self.assertEqual(len(moves), 2)
        self.assertEqual(moves.move_line_ids.lot_id.mapped('name'), ['4250'])
        self.assertAlmostEqual(
            sum(moves.mapped('product_uom_qty')), 8.50, places=2)

    def test_what_the_plugin_does_not_deduct_is_not_born(self):
        """Под минимума / скрап / чужд прът — плъгинът не ги вади, не и тук."""
        self._stock(self.buf, 19.5)
        mo, other = self._mo(), self._mo()
        opt = self._run(mo, [(400.0, 'offcut', [(mo, 6000.0)]),
                             (3000.0, 'scrap', [(mo, 3400.0)]),
                             (4638.0, 'offcut', [(other, 1800.0)])])
        opt._build_cut_allocations()
        self.assertFalse(mo._staged_birth_remnants_at_cut())
        self.assertFalse(self._to_offcut())

    def test_another_birth_mode_is_left_alone(self):
        self._stock(self.buf, 6.5)
        mo = self._mo()
        for mode in ('byproduct', 'inventory'):
            self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])], mode=mode)
            self.assertFalse(mo._staged_birth_remnants_at_cut(),
                             "режим %s не бива да се пипа" % mode)

    # ⑤ ─────────────────────────────────────────────────────────────────
    def test_a_bar_still_on_the_rack_is_not_moved_from_the_rack(self):
        """Прътът още не е в буфера ⇒ нищо не тръгва — и отказът се казва."""
        self._stock(self.rack, 6.5)
        mo = self._mo()
        self._run(mo, [(4638.0, 'offcut', [(mo, 1800.0)])])
        broy = len(mo.message_ids)
        self.assertFalse(mo._staged_birth_remnants_at_cut())
        self.assertFalse(self._to_offcut())
        self.assertAlmostEqual(self._qty(self.rack, self.lot_bar), 6.5, places=2)
        self.assertEqual(len(mo.message_ids), broy + 1, "отказът мълчи")
        self.assertIn('were not born', mo.message_ids[0].body)

    def test_the_cut_is_where_the_birth_is_wired(self):
        """Раждането е вързано в „Produce" (рязането е минало), не в PfP."""
        self._stock(self.buf, 6.5)
        mo = self._mo()
        mo.qty_producing = 1.0
        with patch.object(type(mo), '_staged_birth_remnants_at_cut',
                          return_value=self.env['stock.move']) as razhdane:
            try:
                mo.button_mark_done()
            except Exception:  # noqa: BLE001 — тук се мери само викането
                pass
        self.assertEqual(razhdane.call_count, 1)
