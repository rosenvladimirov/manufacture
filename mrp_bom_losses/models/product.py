# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta
from odoo import api, fields, models, _

import logging
_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    current_bom_id = fields.Many2one('mrp.bom', 'Current version for Bill of Materials')


class ProductProduct(models.Model):
    _inherit = "product.product"

    current_bom_id = fields.Many2one('mrp.bom', 'Current version for Bill of Materials')
