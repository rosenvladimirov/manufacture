# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools, _


class ProductProduct(models.Model):
    _inherit = "product.product"

    description_manufacture = fields.Text('Description for manufacture', translate=True)
    ref_note_manufacture = fields.Char('Manufacture ref note')

    @api.onchange('description_manufacture')
    def onchange_description_manufacture(self):
        for record in self:
            if not record.product_tmpl_id.description_manufacture:
                record.product_tmpl_id.description_manufacture = record.description_manufacture

    @api.onchange('ref_note_manufacture')
    def onchange_ref_note_manufacture(self):
        for record in self:
            if not record.product_tmpl_id.ref_note_manufacture:
                record.product_tmpl_id.ref_note_manufacture = rec.ref_note_manufacture
