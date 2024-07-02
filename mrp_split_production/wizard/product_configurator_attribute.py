# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.addons import decimal_precision as dp

import logging

_logger = logging.getLogger(__name__)


class TemplateSplitConfiguratorAttribute(models.TransientModel):
    _name = 'template.split.configurator.attribute'
    _description = "Split production Product template configurator Attributes"

    split_manage_variant_id = fields.Many2one('wiz.mrp.split.production', 'Split production manage variant wizard')
    product_tmpl_id = fields.Many2one(
        comodel_name='product.template', string='Product Template',
        required=True)
    attribute_id = fields.Many2one(
        comodel_name='product.attribute', string='Attribute', readonly=True)
    value_id = fields.Many2one(
        comodel_name='product.attribute.value',
        domain="[('attribute_id', '=', attribute_id), "
               " ('id', 'in', possible_value_ids)]",
        string='Value')
    possible_value_ids = fields.Many2many(
        comodel_name='product.attribute.value',
        compute='_compute_possible_value_ids',
        readonly=True)
    type_attribute = fields.Selection([('col', 'Use in column'),
                                       ('row', 'Use in rows')],
                                      string="Type")
    system_all = fields.Boolean('Use for all')

    @api.depends('attribute_id')
    def _compute_possible_value_ids(self):
        for record in self:
            # This should be unique due to the new constraint added
            attribute = record.product_tmpl_id.attribute_line_ids.filtered(
                lambda x: x.attribute_id == record.attribute_id)
            record.possible_value_ids = attribute.value_ids.sorted()
