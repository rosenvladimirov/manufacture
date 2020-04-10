# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, exceptions, fields, models, _


class StockMove(models.Model):
    _inherit = 'stock.move'

    operation_ids = fields.One2many("mrp.routing.workcenter", compute="_compute_operation_ids")

    @api.depends('production_id.bom_id')
    def _compute_operation_ids(self):
        for move in self:
            record = []
            for operation in move.production_id.bom_id.mapped("bom_line_ids"):
                record.append(operation.operation_id.id)
            move.operation_ids = False

    @api.model
    def _prepare_account_move_line(self, qty, cost, credit_account_id, debit_account_id):
        res = super(StockMove, self)._prepare_account_move_line(qty, cost, credit_account_id, debit_account_id)
        for line in res:
            if self.production_id:
                line[2]['production_id'] = self.production_id.id
            elif self.raw_material_production_id:
                line[2]['production_id'] = \
                    self.raw_material_production_id.id
            elif self.unbuild_id:
                line[2]['unbuild_order_id'] = self.unbuild_id.id
            elif self.consume_unbuild_id:
                line[2]['unbuild_order_id'] = self.consume_unbuild_id.id
        return res
