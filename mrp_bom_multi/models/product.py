# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    allow_merge = fields.Boolean('Merge productions', help='If checked th procurement will merge all new MO.')
