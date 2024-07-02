#  -*- coding: utf-8 -*-
#  Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, tools, models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    lot_ref = fields.Char('Lot REF', related='lot_id.ref')
