# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    qc_triggers = fields.One2many(comodel_name="qc.trigger.mrp_routing_workcenter_line", inverse_name="operation_id", string="Quality control triggers")
    qc_quantity = fields.Integer("multiple of", default=1)
