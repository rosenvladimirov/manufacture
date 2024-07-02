# -*- coding: utf-8 -*-
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, models, fields, _

class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    #@api.multi
    #@api.depends('costs_overheads_fixed_percentage', 'costs_overheads_variable_percentage')
    #def _compute_hour_real(self):
    #    for rec in self:
    #        rec.costs_hour_real = rec.workcenter_id.costs_hour*(1+rec.workcenter_id.costs_overheads_variable_percentage/100)
    #        rec.costs_hour_fixed_real = rec.workcenter_id.costs_hour_fixed*(1+rec.workcenter_id.costs_overheads_fixed_percentage/100)

    #costs_hour = fields.Float(string='Direct Cost Rate per hour', related="workcenter_id.costs_hour")
    #costs_overheads_variable_percentage = fields.Float(string='Variable OVH Costs %', related="workcenter_id.costs_overheads_variable_percentage")

    #costs_hour_fixed = fields.Float(string='Fixed Direct Cost Rate per hour', related="workcenter_id.costs_hour_fixed")
    #costs_overheads_fixed_percentage = fields.Float(string='Fixed OVH Costs %', related="workcenter_id.costs_overheads_fixed_percentage")

    #costs_hour_real = fields.Float(string="Re-calqulated Direct Cost", compute=_compute_hour_real)
    #costs_hour_fixed_real = fields.Float(string="Re-calqulated Fixed Cost", compute=_compute_hour_real)

    product_id = fields.Many2one(
        'product.product', 'Product Variant',
        domain="[('type', 'in', ['service'])]",
        help="If a product variant is defined the BOM to calculate cost price for operation.")
    resource_type = fields.Selection([
        ('user', 'Human'),
        ('material', 'Material')], string='Resource Type',
        default='material', required=True)

    @api.multi
    def get_time_cycle(self, quantity, product=None ):
        'returneaza timpul per unitate'
        self.ensure_one()
        return self.time_cycle
