# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, exceptions, fields, models, _


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    employee_id = fields.Many2one('hr.employee', string='Worker')

    @api.multi
    def write(self, vals):
        for record in self:
            if record.workorder_id and not self.lot_produced_id and vals.get('lot_produced_id'):
                vals['date'] = fields.Datetime.now
        return super(StockMoveLine, self).write(vals)