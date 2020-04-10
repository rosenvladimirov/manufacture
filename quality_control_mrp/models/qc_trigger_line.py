# -*- coding: utf-8 -*-

from odoo import api, exceptions, fields, models, _


class QcTriggerMRPRoutingWorkcenterLine(models.Model):
    _inherit = "qc.trigger.line"
    _name = "qc.trigger.mrp_routing_workcenter_line"

    operation_id = fields.Many2one(comodel_name="mrp.routing.workcenter")

    def get_trigger_line_for_event(self, trigger, operation=False, product=False, partner=False, qty=1):
        trigger_lines = super(
            QcTriggerMRPRoutingWorkcenterLine,self).get_trigger_line_for_event(trigger, operation=operation, product=product, partner=partner, qty=qty)
        for trigger_line in product.product_tmpl_id.qc_triggers.filtered(
                lambda r: r.trigger == trigger and (r.quantity//qty == r.quantity/qty or operation.qc_quantity//qty == operation.qc_quantity/qty) and (
                not r.partners or not partner or
                partner.commercial_partner_id in r.partners) and
                r.test.active):
            trigger_lines.add(trigger_line)
        return trigger_lines

