# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from itertools import groupby
import logging

from odoo.exceptions import UserError, RedirectWarning

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    buffer_workorder_id = fields.Many2one('mrp.workorder', 'Work Order', check_company=True)

    def _check_for_buffering(self):
        if self.workorder_id and self.workorder_id.use_buffering and self.lot_id:
            lot_id = self.lot_id
            lot_name = self.lot_name
            qty_done = self.qty_done
            wo = self.workorder_id
            if not self.move_id.move_line_ids.filtered(lambda r: r.buffer_workorder_id == wo and r.product_id == self.product_id and r.lot_id == self.lot_id):
                res_move_line = self._convert_to_write(self._cache)
                _logger.info("RES_MOVE_LINE %s" % res_move_line)
                res_move_line.update({
                    # 'qty_done': qty_done,
                    # 'workorder_id': False,
                    'buffer_workorder_id': wo.id,
                })
                wo.buffered_move_line_ids += self.env['stock.move.line'].new(res_move_line)

            if not wo.buffer_product_ids.filtered(lambda r: r.lot_id == lot_id and r.final_lot_id == wo.final_lot_id):
                wo.buffer_product_ids += self.env['mrp.workorder.buffer'].new({
                    'product_id': self.product_id.id,
                    'workorder_id': wo.id,
                    'operation_id': wo.operation_id.id,
                    'lot_id': lot_id and lot_id.id or False,
                    'lot_name': lot_name,
                    'final_product_id': wo.product_id.id,
                    'final_lot_id': wo.final_lot_id and wo.final_lot_id.id or False,
                    'qty_done': qty_done,
                    'qty_producing': wo.qty_producing,
                })

    @api.onchange('lot_name', 'lot_id')
    @api.depends('workorder_id.buffer_product_ids', 'workorder_id.active_move_line_ids')
    def onchange_serial_number(self):
        res = super(StockMoveLine, self).onchange_serial_number()
        for record in self:
            if (record.lot_id or record.lot_name) \
                    and record.workorder_id \
                    and record.workorder_id.use_buffering \
                    and not self._context.get('no_check_buffering', False):
                # _logger.info("TEST FOR LOT %s" % record.lot_id and record.lot_id.name)
                record._check_for_buffering()
                record.lot_id = False
                record.workorder_id.work_component = False
        return res
