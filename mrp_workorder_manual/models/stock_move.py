# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, exceptions, fields, models, _


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    employee_id = fields.Many2one('hr.employee', string='Worker')

    @api.onchange('lot_id', 'move_id.workorder_id')
    def onchange_lot_id(self):
        self.ensure_one()
        if self.lot_id and self.move_id.workorder_id and self._context.get('use_bin', False):
            workorder = self.move_id.workorder_id
            move_use_ids = workorder and workorder.mapped('move_bin_ids').filtered(lambda r: r.product_id == self.product_id)
            if move_use_ids:
                for move in move_use_ids:
                    move.lot_id = self.lot_id
