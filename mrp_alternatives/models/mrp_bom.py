# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    skip_alternative = fields.Boolean('Skip using material')
    alternative_component_ids = fields.Many2many('product.product', related='product_id.alternative_component_ids',
                                                 string='Alternatives')
