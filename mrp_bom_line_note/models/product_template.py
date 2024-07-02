# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools, _

class ProductTemplate(models.Model):
    _inherit = "product.template"

    description_manufacture = fields.Text('Description for manufacture', translate=True)
    ref_note_manufacture = fields.Char('Manufacture ref note')
