# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _, Command


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    lot_dynamic = fields.Boolean(
        string='Lot Dynamic',
        default=False,
        help='Indicates if the BOM line is dynamically adjusted based on lot-specific requirements.'
    )
