# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, fields, models
from odoo.addons import decimal_precision as dp

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    own_mrp_component = fields.Boolean('Own for production',
                                       help='If checked this product will not used in MRP calculations.')
    own_mrp_produced = fields.Boolean('Own materials',
                                      help='If checked this product will use in MRP calculations own components.')


class Product(models.Model):
    _inherit = "product.product"

    own_value = fields.Float(string='Own Value', compute='_compute_own_value')
    own_standard_price = fields.Float(string='Own Cost', digits=dp.get_precision('Product Price'))
    own_fifo_move_ids = fields.Many2many('stock.move', compute='_compute_own_value')

    @api.multi
    @api.depends('stock_move_ids.product_qty', 'stock_move_ids.state', 'stock_move_ids.remaining_value',
                 'product_tmpl_id.cost_method', 'product_tmpl_id.standard_price', 'product_tmpl_id.property_valuation',
                 'product_tmpl_id.categ_id.property_valuation')
    def _compute_own_value(self):
        StockMove = self.env['stock.move']
        to_date = self.env.context.get('to_date')

        product_values = {product.id: 0 for product in self}
        product_quantity = {product.id: 0 for product in self}
        product_move_ids = {product.id: [] for product in self}

        if to_date:
            domain = [('product_id', 'in', self.ids), ('date', '<=', to_date)] + StockMove._get_all_base_domain()
            value_field_name = 'own_value'
        else:
            domain = [('product_id', 'in', self.ids)] + StockMove._get_all_base_domain()
            value_field_name = 'own_value'

        StockMove.check_access_rights('read')
        query = StockMove._where_calc(domain)
        StockMove._apply_ir_rules(query, 'read')
        from_clause, where_clause, params = query.get_sql()
        where_clause += ' AND pt.own_mrp_produced = TRUE '
        query_str = """
            SELECT stock_move.product_id, SUM(COALESCE(stock_move.{}, 0.0)), ARRAY_AGG(stock_move.id)
            FROM {} 
            LEFT JOIN product_product pp ON (stock_move.product_id = pp.id)
            LEFT JOIN product_template pt ON (pp.product_tmpl_id = pt.id)
            WHERE {}
            GROUP BY stock_move.product_id
        """.format(value_field_name, from_clause, where_clause)
        self.env.cr.execute(query_str, params)
        # _logger.info("SQL %s" % query_str)
        # _logger.info("FROM %s" % from_clause)
        # _logger.info("CLAUSE %s" % where_clause)
        # _logger.info("PARAMS %s" % (params, ))
        # query_str_end = query_str % tuple(params)
        # _logger.info("TOTAL SQL %s", query_str_end)
        for product_id, value, move_ids in self.env.cr.fetchall():
            move_line_ids = self.env['stock.move.line'].search([('move_id', 'in', move_ids)])
            product_values[product_id] = value
            product_quantity[product_id] = sum([x.qty_done for x in move_line_ids])
            product_move_ids[product_id] = move_ids
            # _logger.info("PRODUCT %s:%s:%s" % (product_id, value, move_ids))

        for product in self:
            qty_available = product.with_context(company_owned=True, owner_id=False).qty_available
            if product.cost_method == 'fifo':
                product.own_value = product_values[product.id]
                product.own_fifo_move_ids = StockMove.browse(product_move_ids[product.id])
                if qty_available != 0.0:
                    product.own_standard_price = product_values[product.id] / qty_available
                elif product_quantity[product.id] != 0.0:
                    product.own_standard_price = product_values[product.id] / product_quantity[product.id]
            else:
                product.own_value = product.own_standard_price * qty_available
