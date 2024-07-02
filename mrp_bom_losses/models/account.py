# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, models, fields, _


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    production_id = fields.Many2one(comodel_name='mrp.production', string='Manufacture Order', copy=False,index=True)
    unbuild_order_id = fields.Many2one(comodel_name='mrp.unbuild', string='Unbuild Order', copy=False, index=True)