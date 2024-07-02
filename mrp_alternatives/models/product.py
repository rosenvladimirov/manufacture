# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools, _


class ProductTemplate(models.Model):
    _inherit = "product.template"

    alternative_component_ids = fields.Many2many('product.template', 'product_alternative_component_rel', 'src_id',
                                                 'dest_id',
                                                 string='Alternative Components',
                                                 help='Suggest more expensive alternatives to '
                                                      'components. Those products to be possible to replace is scheme.')


class ProductProduct(models.Model):
    _inherit = "product.product"

    alternative_component_ids = fields.Many2many('product.product', 'product_alternative_product',
                                                 'src_id',
                                                 'dest_id',
                                                 string='Alternative components')

    @api.onchange('alternative_component_ids')
    def onchange_alternative_component_ids(self):
        for record in self:
            if record.product_tmpl_id and len(record.alternative_component_ids.ids) > 0:
                record.product_tmpl_id.alternative_component_ids = record.alternative_component_ids.mapped('product_tmpl_id')
