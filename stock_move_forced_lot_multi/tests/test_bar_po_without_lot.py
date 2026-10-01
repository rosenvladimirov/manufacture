# -*- coding: utf-8 -*-
"""Прът по лот в покупка без форсиран лот — казва се (№118, 01.10).

Мерено на fulltest: покупка 1741 за ETE E 41103 излезе без лот, защото и
седемте сурови движения на МО бяха без лот (празен Default Forced Lot в
рецептите) — точката нямаше какво да събере. Приемането спря, нищо не
беше казано по-рано.

Тук се пази:
  ① прът по лот без лот ⇒ бележка в покупката, с кода на продукта;
  ② с форсиран лот ⇒ тихо;
  ③ продукт по лот, който не е прът (стъкло, Armafom) ⇒ тихо;
  ④ втори ред без лот за същия продукт ⇒ без втора бележка.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBarPoWithoutLot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.has_bar_field = 'bar_length_mm' in cls.env['stock.lot']._fields
        cls.vendor = cls.env['res.partner'].create({'name': 'T118 vendor'})
        cls.bar = cls._product('T118 sill bar', 'T118-BAR')
        cls.glass = cls._product('T118 glass unit', 'T118-GLS')
        Lot = cls.env['stock.lot']
        cls.lot = Lot.create({'name': '6300', 'product_id': cls.bar.id,
                              'company_id': cls.env.company.id})
        if cls.has_bar_field:
            cls.lot.bar_length_mm = 6300.0
        Lot.create({'name': 'G-1', 'product_id': cls.glass.id,
                    'company_id': cls.env.company.id})
        cls.dest = cls.env.ref('stock.stock_location_stock')

    @classmethod
    def _product(cls, name, code):
        product = cls.env['product.product'].create({
            'name': name, 'default_code': code, 'is_storable': True,
            'tracking': 'lot'})
        cls.env['product.supplierinfo'].create({
            'partner_id': cls.vendor.id,
            'product_tmpl_id': product.product_tmpl_id.id, 'price': 1.0})
        return product

    def setUp(self):
        super().setUp()
        if not self.has_bar_field:
            self.skipTest('bar_length_mm (плъгинът за разкроя) не е инсталиран')
        self.po = self.env['purchase.order'].create(
            {'partner_id': self.vendor.id})

    def _line_vals(self, product, values=None):
        values = dict(values or {})
        values.setdefault('supplier', product.seller_ids[:1])
        return self.env['purchase.order.line'] \
            ._prepare_purchase_order_line_from_procurement(
                product, 6.3, product.uom_id, self.dest, product.name,
                'T118', self.env.company, values, self.po)

    def _notes(self):
        return self.po.message_ids.filtered(lambda m: 'T118-' in (m.body or ''))

    def test_a_bar_without_a_lot_is_said(self):
        self._line_vals(self.bar)
        self.assertEqual(len(self._notes()), 1, 'прът без лот мина тихо')
        self.assertIn('[T118-BAR]', self._notes().body)

    def test_a_bar_with_a_forced_lot_is_quiet(self):
        vals = self._line_vals(self.bar, {'forced_lot_ids': self.lot})
        self.assertEqual(vals['forced_lot_ids'], [(6, 0, self.lot.ids)])
        self.assertFalse(self._notes())

    def test_a_lot_product_that_is_not_a_bar_is_quiet(self):
        self._line_vals(self.glass)
        self.assertFalse(self._notes(), 'стъкло/Armafom не са пръти')

    def test_a_second_line_without_a_lot_is_not_said_twice(self):
        self.env['purchase.order.line'].create(
            dict(self._line_vals(self.bar), order_id=self.po.id))
        self._line_vals(self.bar)
        self.assertEqual(len(self._notes()), 1, 'бележката се повтаря')
