# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _

import logging

_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    def _generate_lot_ids(self):
        super(MrpWorkorder, self)._generate_lot_ids()
        # _logger.info("_generate_lot_ids %s:%s" % (self.production_id.stock_move_lines_ids,
        #                                           self.move_raw_ids.mapped('move_line_ids')))
        if self.use_bins:
            return
        if len(self.active_move_line_ids.ids) > 0 \
                and len(self.production_id.stock_move_lines_ids.ids) > 0 \
                and len(
            self.production_id.move_raw_ids.filtered(lambda r: r.operation_id == self.operation_id).ids) > 0:
            product_qty = {}
            stock_move_lines_ids = self.production_id.stock_move_lines_ids.mapped('product_id').ids
            active_line_unlink_ids = self.env['stock.move.line']
            used_special_qty_ids = self.production_id.move_raw_ids. \
                filtered(lambda r: r.operation_id == self.operation_id and r.needs_lots)
            for move_id in used_special_qty_ids:
                if move_id.location_id != self.production_id.location_src_id:
                    move_id.location_id = self.production_id.location_src_id
                if not product_qty.get(move_id.product_id):
                    product_qty[move_id.product_id] = {}
                product_qty[move_id.product_id][move_id] = {}
                for line in move_id.mapped('move_line_ids'). \
                        sorted(lambda r: "%s-%s" % (r.product_id.id, r.lot_id and r.lot_id.id or 0)). \
                        filtered(lambda r: r.lot_id and r.product_id.id in
                                           stock_move_lines_ids and (r.done_wo or r.product_qty > 0.0)):
                    if not product_qty[move_id.product_id][move_id].get(line.lot_id):
                        product_qty[move_id.product_id][move_id][line.lot_id] = (0.0, 0.0, False, False)
                    product_qty[move_id.product_id][move_id][line.lot_id] = (
                        product_qty[move_id.product_id][move_id][line.lot_id][0] + line.product_qty,
                        product_qty[move_id.product_id][move_id][line.lot_id][1] + line.qty_done,
                        line,
                    )
            # _logger.info("MOVES_LOTS %s" % product_qty)
            for product_id, move_ids in product_qty.items():
                for move_id, lot_ids in move_ids.items():
                    qty_to_use = 0.0
                    for lot_id, line in dict(sorted(lot_ids.items(), key=lambda item: item[0].name)).items():
                        # _logger.info(
                        #     "PRODUCT-ALL-LOT %s:%s" % (product_id.display_name, lot_id and lot_id.name or 'None'))

                        if not lot_id:
                            for line_for_check in line[2]:
                                if line_for_check.product_id.tracking != 'none':
                                    active_line_unlink_ids |= line_for_check
                            continue
                        active_line_not_lot_ids = self.active_move_line_ids. \
                            filtered(
                            lambda r: r.product_id == product_id and r.product_id.tracking != 'none' and not r.lot_id)
                        active_line_lot_ids = self.active_move_line_ids. \
                            filtered(lambda r: r.product_id == product_id and r.lot_id == lot_id and r.qty_done != 0.0)
                        # move_id = line[2].move_id
                        qty_done = (move_id.unit_factor * self.qty_producing) - qty_to_use
                        qty_rest = line[0] - line[1]
                        if qty_rest > 0.0:
                            qty_to_use += qty_rest > qty_done and qty_done or qty_rest
                        # _logger.info("PRODUCT-LOT %s:%s(%s=%s=%s<%s)" % (
                        # product_id.display_name, lot_id.name, qty_rest, move_id.unit_factor * self.qty_producing,
                        # qty_to_use, qty_done))
                        if qty_rest > 0 and qty_done > 0.0:
                            # if self.use_bins:
                            #     if not self.split_lot_ids. \
                            #             filtered(lambda r: r.product_id == move_id.product_id and r.lot_id == lot_id):
                            #         self.split_lot_ids += self.env['stock.production.lot.save'].new({
                            #             'lot_id': lot_id.id,
                            #             'production_id': self.production_id.id,
                            #             'workorder_id': self.id,
                            #             'operation_id': self.operation_id.id,
                            #             'product_id': move_id.product_id.id,
                            #             'qty_done': qty_rest > qty_done and qty_done or qty_rest,
                            #         })

                            if active_line_not_lot_ids:
                                active_line_not_lot_ids.write({
                                    'lot_id': lot_id.id,
                                    'qty_done': qty_rest > qty_done and qty_done or qty_rest,
                                })
                            elif active_line_lot_ids:
                                active_line_lot_ids.write({
                                    'qty_done': qty_rest > qty_done and qty_done or qty_rest,
                                })
                            else:
                                active_line_lot_ids = self.env['stock.move.line'].create({
                                    'move_id': move_id.id,
                                    'product_uom_qty': 0,
                                    'product_uom_id': move_id.product_uom.id,
                                    'qty_done': qty_rest > qty_done and qty_done or qty_rest,
                                    'product_id': move_id.product_id.id,
                                    'production_id': self.production_id.id,
                                    'workorder_id': self.id,
                                    'done_wo': False,
                                    'location_id': move_id.location_id.id,
                                    'location_dest_id': move_id.location_dest_id.id,
                                    'lot_id': lot_id.id,
                                })
                        else:
                            active_line_unlink_ids |= active_line_lot_ids

            if self._context.get('force_produce'):
                for line in self.active_move_line_ids. \
                        filtered(lambda r: r.product_id.tracking != 'none' and not r.lot_id and r.qty_done != 0.0):
                    active_line_unlink_ids |= line

            active_line_unlink_ids |= self.active_move_line_ids. \
                filtered(lambda r: r.product_id.id in stock_move_lines_ids \
                                   and r.product_id.tracking != 'none' \
                                   and not r.lot_id and r.qty_done != 0.0)
            for line in active_line_unlink_ids:
                line.unlink()

    @api.multi
    def button_empty_bins(self):
        super(MrpWorkorder, self).button_empty_bins()
        for record in self:
            if not record.use_bins and len(self.production_id.stock_move_lines_ids.ids) > 0:
                record.active_move_line_ids = False
                record._generate_lot_ids()
