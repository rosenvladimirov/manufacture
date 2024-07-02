# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, models, fields, _


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    production_id = fields.Many2one('mrp.production')
