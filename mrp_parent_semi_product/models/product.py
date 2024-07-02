#  -*- coding: utf-8 -*-
#  Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools, _


class ProductProduct(models.Model):
    _inherit = "product.product"

    parent_product_id = fields.Many2one('product.product', 'Product Variant', index=True)
