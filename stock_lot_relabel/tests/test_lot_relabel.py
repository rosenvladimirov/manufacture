# -*- coding: utf-8 -*-
"""Смяна на лота на място — през „Lot Relabel", с равна стойност (№93).

Пази се:
  ① две валидирани движения, една референция, сочат се взаимно; не са
    инвентаризация и не са брак; лотът-източник намалява, лотът-цел расте;
  ② стойността на входа е ТОЧНО тази на изхода — и при ДВА FIFO слоя с
    различна цена; общата стойност на продукта не мърда;
  ③ счетоводните редове са по двете настроени сметки на локацията, срещу
    сметката на склада на категорията — не по входа/изхода на категорията;
  ④ празни сметки при автоматична оценка ⇒ отказ, нищо не се записва;
  ⑤ несвободно количество ⇒ отказ.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLotRelabel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang='en_US'))
        cls.company = cls.env.company
        Account = cls.env['account.account']

        def acc(code, name):
            return Account.create({'code': code, 'name': name,
                                   'account_type': 'asset_current'})
        cls.acc_in = acc('T93RIN', 'T93R stock input')
        cls.acc_out = acc('T93ROUT', 'T93R stock output')
        cls.acc_val = acc('T93RVAL', 'T93R stock valuation')
        cls.acc_rel_in = acc('T93RLIN', 'T93R relabel incoming')
        cls.acc_rel_out = acc('T93RLOUT', 'T93R relabel outgoing')
        cls.journal = cls.env['account.journal'].create({
            'name': 'T93R stock', 'code': 'T93RJ', 'type': 'general'})
        cls.categ = cls.env['product.category'].create({
            'name': 'T93R bars',
            'property_cost_method': 'fifo',
            'property_valuation': 'real_time',
            'property_stock_account_input_categ_id': cls.acc_in.id,
            'property_stock_account_output_categ_id': cls.acc_out.id,
            'property_stock_valuation_account_id': cls.acc_val.id,
            'property_stock_journal': cls.journal.id,
        })
        cls.meter = cls.env.ref('uom.product_uom_meter')
        cls.bar = cls.env['product.product'].create({
            'name': 'PVC frame T93REL', 'is_storable': True, 'tracking': 'lot',
            'categ_id': cls.categ.id,
            'uom_id': cls.meter.id, 'uom_po_id': cls.meter.id})
        cls.wh = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.buf = cls.env['stock.location'].create({
            'name': 'Pre-Production T93REL', 'usage': 'internal',
            'location_id': cls.wh.lot_stock_id.id})
        Lot = cls.env['stock.lot']
        cls.lot_bar = Lot.create({'name': 'T93REL-6500',
                                  'product_id': cls.bar.id,
                                  'company_id': cls.company.id})
        cls.lot_rem = Lot.create({'name': 'T93REL-4630',
                                  'product_id': cls.bar.id,
                                  'company_id': cls.company.id})
        cls.relabel_loc = cls.company._get_lot_relabel_location()
        cls.relabel_loc.write({
            'valuation_in_account_id': cls.acc_rel_in.id,
            'valuation_out_account_id': cls.acc_rel_out.id,
        })
        cls.supplier = cls.env.ref('stock.stock_location_suppliers')

    def _receive(self, qty, price, lot=None):
        move = self.env['stock.move'].create({
            'name': 'T93REL receipt', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': qty,
            'price_unit': price, 'location_id': self.supplier.id,
            'location_dest_id': self.buf.id})
        move._action_confirm()
        move.move_line_ids.unlink()     # редът на ядрото е без лот
        self.env['stock.move.line'].create({
            'move_id': move.id, 'product_id': self.bar.id,
            'product_uom_id': self.meter.id, 'location_id': self.supplier.id,
            'location_dest_id': self.buf.id,
            'lot_id': (lot or self.lot_bar).id, 'quantity': qty,
            'picked': True})
        move.picked = True
        move._action_done()
        return move

    def _qty(self, lot):
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', self.bar.id), ('lot_id', '=', lot.id),
            ('location_id', '=', self.buf.id)]).mapped('quantity'))

    def _relabel(self, qty, ref='T93REL · P53: 6500 → 4630'):
        return self.env['stock.lot']._relabel(
            self.bar, qty, self.buf, self.lot_bar, self.lot_rem, ref)

    # ① ─────────────────────────────────────────────────────────────────
    def test_two_moves_with_one_trace(self):
        self._receive(10.0, 3.33)
        moves = self._relabel(4.63)
        out, inn = moves
        self.assertEqual((out.lot_relabel_role, inn.lot_relabel_role),
                         ('out', 'in'))
        self.assertEqual(moves.mapped('state'), ['done', 'done'])
        self.assertEqual(out.location_id, self.buf)
        self.assertEqual(out.location_dest_id, self.relabel_loc)
        self.assertEqual(inn.location_id, self.relabel_loc)
        self.assertEqual(inn.location_dest_id, self.buf)
        self.assertEqual(out.lot_relabel_pair_id, inn)
        self.assertEqual(inn.lot_relabel_pair_id, out)
        self.assertEqual(set(moves.mapped('reference')),
                         {'T93REL · P53: 6500 → 4630'})
        self.assertEqual(out.move_line_ids.lot_id, self.lot_bar)
        self.assertEqual(inn.move_line_ids.lot_id, self.lot_rem)
        self.assertFalse(any(moves.mapped('is_inventory')))
        self.assertFalse(any(moves.mapped('scrapped')))
        self.assertEqual(self.relabel_loc.usage, 'inventory')
        self.assertEqual(self.relabel_loc.company_id, self.company)
        self.assertNotEqual(
            self.relabel_loc, self.bar.with_company(
                self.company).property_stock_inventory,
            "преетикетирането минава през инвентаризацията")
        self.assertAlmostEqual(self._qty(self.lot_bar), 5.37, places=2)
        self.assertAlmostEqual(self._qty(self.lot_rem), 4.63, places=2)

    # ② ─────────────────────────────────────────────────────────────────
    def test_value_in_equals_value_out_one_layer(self):
        self._receive(10.0, 3.33)
        out, inn = self._relabel(4.63)
        v_out = sum(out.stock_valuation_layer_ids.mapped('value'))
        v_in = sum(inn.stock_valuation_layer_ids.mapped('value'))
        self.assertAlmostEqual(v_out, -15.42, places=2)   # 4,63 × 3,33
        self.assertAlmostEqual(v_in, 15.42, places=2)
        self.assertEqual(self.company.currency_id.compare_amounts(v_in, -v_out),
                         0)

    def test_value_in_equals_value_out_two_fifo_layers(self):
        """Изход 6,30 м от два слоя: 5 × 3,00 + 1,30 × 3,20 = 19,16.

        Средната цена 3,0412698… е безкрайна дроб. Входът е 19,16 — не
        `standard_price` × 6,30 и не „закръглената средна" × 6,30."""
        self._receive(5.0, 3.00)
        self._receive(5.0, 3.20)
        value_before = self.bar.with_company(self.company).value_svl
        out, inn = self._relabel(6.3)
        v_out = sum(out.stock_valuation_layer_ids.mapped('value'))
        v_in = sum(inn.stock_valuation_layer_ids.mapped('value'))
        self.assertAlmostEqual(v_out, -19.16, places=2,
                               msg="FIFO не изведе от двата слоя")
        self.assertAlmostEqual(v_in, 19.16, places=2,
                               msg="входът не е стойността на изхода")
        self.assertEqual(self.company.currency_id.compare_amounts(v_in, -v_out),
                         0)
        layer = inn.stock_valuation_layer_ids
        self.assertAlmostEqual(layer.remaining_value, 19.16, places=2)
        self.assertAlmostEqual(layer.remaining_qty, 6.3, places=2)
        self.bar.invalidate_recordset(['value_svl'])
        self.assertAlmostEqual(
            self.bar.with_company(self.company).value_svl, value_before,
            places=2, msg="преетикетирането промени стойността на склада")

    # ③ ─────────────────────────────────────────────────────────────────
    def test_entries_use_the_two_relabel_accounts(self):
        self._receive(5.0, 3.00)
        self._receive(5.0, 3.20)
        out, inn = self._relabel(6.3)
        aml_out = out.stock_valuation_layer_ids.account_move_id.line_ids
        aml_in = inn.stock_valuation_layer_ids.account_move_id.line_ids
        self.assertEqual(aml_out.account_id, self.acc_val | self.acc_rel_in)
        self.assertEqual(aml_in.account_id, self.acc_val | self.acc_rel_out)
        dr = aml_out.filtered(lambda l: l.account_id == self.acc_rel_in)
        cr = aml_out.filtered(lambda l: l.account_id == self.acc_val)
        self.assertAlmostEqual(dr.debit, 19.16, places=2)
        self.assertAlmostEqual(cr.credit, 19.16, places=2)
        dr = aml_in.filtered(lambda l: l.account_id == self.acc_val)
        cr = aml_in.filtered(lambda l: l.account_id == self.acc_rel_out)
        self.assertAlmostEqual(dr.debit, 19.16, places=2)
        self.assertAlmostEqual(cr.credit, 19.16, places=2)
        self.assertFalse(
            (aml_out | aml_in).account_id & (self.acc_in | self.acc_out),
            "падна към входа/изхода на категорията")

    # ④ ─────────────────────────────────────────────────────────────────
    def test_missing_accounts_refuse_for_real_time(self):
        self._receive(10.0, 3.33)
        for field in ('valuation_in_account_id', 'valuation_out_account_id'):
            keep = self.relabel_loc[field]
            self.relabel_loc[field] = False
            n_moves = self.env['stock.move'].search_count([])
            with self.assertRaisesRegex(UserError, 'valuation account'):
                self._relabel(4.63)
            self.assertEqual(self.env['stock.move'].search_count([]), n_moves)
            self.relabel_loc[field] = keep
        self.assertAlmostEqual(self._qty(self.lot_bar), 10.0, places=2)

    def test_periodic_valuation_needs_no_accounts(self):
        self.categ.property_valuation = 'manual_periodic'
        self.relabel_loc.write({'valuation_in_account_id': False,
                                'valuation_out_account_id': False})
        self._receive(10.0, 3.33)
        out, inn = self._relabel(4.63)
        self.assertFalse(out.stock_valuation_layer_ids.account_move_id)
        self.assertAlmostEqual(
            sum(inn.stock_valuation_layer_ids.mapped('value')), 15.42, places=2)

    # ⑤ ─────────────────────────────────────────────────────────────────
    def test_reserved_stock_is_not_relabelled(self):
        self._receive(6.5, 3.00)
        other = self.env['stock.move'].create({
            'name': 'T93REL consumer', 'product_id': self.bar.id,
            'product_uom': self.meter.id, 'product_uom_qty': 3.0,
            'location_id': self.buf.id,
            'location_dest_id': self.env.ref(
                'stock.stock_location_customers').id})
        other._action_confirm()
        other._action_assign()
        self.assertAlmostEqual(other.quantity, 3.0, places=2)
        with self.assertRaisesRegex(UserError, 'is free'):
            self._relabel(4.63)
        self.assertAlmostEqual(other.quantity, 3.0, places=2,
                               msg="преетикетирането открадна резервация")
