#  -*- coding: utf-8 -*-
#  Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools, _


class ProductTemplate(models.Model):
    _inherit = "product.template"

    use_ref = fields.Boolean('Use internal reference')
    product_populate_ids = fields.One2many('product.populate.product',
                                           string='Product Populate',
                                           compute="_compute_product_populate_ids")

    @api.multi
    def _compute_product_populate_ids(self):
        for record in self:
            record.product_populate_ids = self.env['product.populate.product']
            for product_id in record.product_variant_ids:
                for populate in product_id.product_populate_ids:
                    record.product_populate_ids |= populate


class ProductProduct(models.Model):
    _inherit = "product.product"

    product_populate_ids = fields.One2many('product.populate.product',
                                           inverse_name='product_id',
                                           string='Product Populate')


class ProductPopulateProduct(models.Model):
    _name = "product.populate.product"
    _description = "Product Populate Product"
    _rec_name = "name"

    name = fields.Char(string="Name", compute="_compute_name", store=True)
    product_id = fields.Many2one("product.product", string="Product", ondelete="cascade", index=True, required=True)
    product_populate_id = fields.Many2one('product.product', string="Product Populate", required=True)

    @api.multi
    @api.depends('product_id', 'product_populate_id')
    def _compute_name(self):
        for record in self:
            record.name = f"{record.product_id.name} - {record.product_populate_id.name}"
