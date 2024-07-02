# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools, _


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ref_lot_pair_ids = fields.Many2many('product.product', string='Pair products', compute='_compute_ref_lot_pair_ids')

    @api.multi
    def _compute_ref_lot_pair_ids(self):
        for record in self:
            if record.product_variant_count > 1:
                record.ref_lot_pair_ids = record.product_variant_ids.mapped('ref_lot_pair_ids')
            else:
                record.ref_lot_pair_ids = record.ref_lot_pair_ids


class ProductProduct(models.Model):
    _inherit = "product.product"

    ref_lot = fields.Char('Expression')
    ref_lot_pair_ids = fields.Many2many('product.product', 'product_pair_product_rel',
                                        'src_id', 'dest_id', string='Pair products')
    print_label_id = fields.Many2one('ir.actions.report', string='Report for print')
