# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class Picking(models.Model):
    _inherit = "stock.picking"

    production_ids = fields.Many2many(
        comodel_name='mrp.production',
        relation='mrp_production_stock_picking_rel',
        column1='stock_picking_id',
        column2='mrp_production_id',
        string='Productions',
    )

    @api.multi
    def update_productions(self):
        for record in self:
            for line in record.move_line_ids:
                line.production_ids = [(6, False, record.production_ids.ids)]

    @api.multi
    def mrp_action_assign(self):
        for record in self:
            if record.state == 'done':
                for production in record.production_ids:
                    production.action_assign()
        return True
