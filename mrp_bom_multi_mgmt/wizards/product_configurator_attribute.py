# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.addons import decimal_precision as dp

import logging

_logger = logging.getLogger(__name__)


class TemplateBomConfiguratorAttribute(models.TransientModel):
    _name = 'template.bom.configurator.attribute'
    _description = "Product template configurator Attributes"

    bom_manage_variant_id = fields.Many2one('bom.manage.variant', 'BOM manage variant wizard')
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
    price_extra = fields.Float(
        compute='_compute_price_extra',
        digits=dp.get_precision('Product Price'),
        help="Price Extra: Extra price for the variant with this attribute "
             "value on sale price. eg. 200 price extra, 1000 + 200 = 1200.")

    system_all = fields.Boolean('Use for all')

    @api.depends('attribute_id')
    def _compute_possible_value_ids(self):
        for record in self:
            # This should be unique due to the new constraint added
            attribute = record.product_tmpl_id.attribute_line_ids.filtered(
                lambda x: x.attribute_id == record.attribute_id)
            record.possible_value_ids = attribute.value_ids.sorted()

    @api.depends('value_id')
    def _compute_price_extra(self):
        for record in self:
            record.price_extra = sum(
                record.value_id.price_ids.filtered(
                    lambda x: (
                        x.product_tmpl_id == record.product_tmpl_id)
                ).mapped('price_extra'))


class ComponentBomConfiguratorAttribute(models.TransientModel):
    _name = 'component.bom.configurator.attribute'
    _description = "Component Product template configurator Attributes"

    bom_manage_variant_id = fields.Many2one('bom.manage.variant', 'BOM manage variant wizard')
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
    price_extra = fields.Float(
        compute='_compute_price_extra',
        digits=dp.get_precision('Product Price'),
        help="Price Extra: Extra price for the variant with this attribute "
             "value on sale price. eg. 200 price extra, 1000 + 200 = 1200.")

    system_all = fields.Boolean('Use for all')

    @api.depends('attribute_id')
    def _compute_possible_value_ids(self):
        for record in self:
            # This should be unique due to the new constraint added
            attribute = record.product_tmpl_id.attribute_line_ids.filtered(
                lambda x: x.attribute_id == record.attribute_id)
            record.possible_value_ids = attribute.value_ids.sorted()

    @api.depends('value_id')
    def _compute_price_extra(self):
        for record in self:
            record.price_extra = sum(
                record.value_id.price_ids.filtered(
                    lambda x: (
                        x.product_tmpl_id == record.product_tmpl_id)
                ).mapped('price_extra'))
