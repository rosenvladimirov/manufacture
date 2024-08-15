# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _, tools


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    name = fields.Char(translate=True)
