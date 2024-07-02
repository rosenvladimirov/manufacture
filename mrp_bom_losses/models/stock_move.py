# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, exceptions, fields, models, _
from odoo.addons.queue_job.job import job

import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    operation_ids = fields.One2many("mrp.routing.workcenter", compute="_compute_operation_ids")
    own_value = fields.Float(copy=False)
    own_price_unit = fields.Float(
        'Own Unit Price',
        help="Technical field used to record the product cost set by the user during a picking confirmation (when "
             "costing method used is 'average price' or 'real'). Value given in company currency and in product uom.",
        copy=False)  # as it's a technical field, we intentionally don't provide the digits attribute

    @api.depends('production_id.bom_id', 'raw_material_production_id')
    @api.multi
    def _compute_operation_ids(self):
        for move in self:
            move.operation_ids = self.env['mrp.routing.workcenter']
            if move.raw_material_production_id:
                for operation in move.raw_material_production_id.bom_id.mapped("bom_line_ids"):
                    move.operation_ids |= operation.operation_id

    @api.multi
    def _get_accounting_data_for_valuation(self):
        journal_id, acc_src, acc_dest, acc_valuation = super(StockMove, self)._get_accounting_data_for_valuation()
        for record in self:
            if record.product_id.own_mrp_component and record.location_dest_id.val_own_in_account_id:
                acc_dest = record.location_dest_id.val_own_in_account_id.id
        return journal_id, acc_src, acc_dest, acc_valuation

    @api.model
    def _prepare_account_move_line(self, qty, cost, credit_account_id, debit_account_id):
        res = super(StockMove, self)._prepare_account_move_line(qty, cost, credit_account_id, debit_account_id)
        for line in res:
            if self.production_id:
                line[2]['production_id'] = self.production_id.id
                if self.production_id.analytic_account_id:
                    line[2]['analytic_account_id'] = self.production_id.analytic_account_id.id
            elif self.raw_material_production_id:
                line[2]['production_id'] = \
                    self.raw_material_production_id.id
                if self.raw_material_production_id.analytic_account_id:
                    line[2]['analytic_account_id'] = self.raw_material_production_id.analytic_account_id.id
            elif self.unbuild_id:
                line[2]['unbuild_order_id'] = self.unbuild_id.id
            elif self.consume_unbuild_id:
                line[2]['unbuild_order_id'] = self.consume_unbuild_id.id
        return res

    @api.multi
    def _account_entry_move(self):
        self.ensure_one()
        res = super(StockMove, self)._account_entry_move()
        if res is not None and not res:
            # `super()` tends to `return False` as an indicator that no
            # valuation should happen in this case
            return res
        for move in self:
            if not move.workorder_id:
                continue
            if move.restrict_partner_id:
                continue
            if move.product_id.type != 'consu':
                continue
            price_unit = move.price_unit
            if move.workorder_id and move.product_id == move.workorder_id.operation_id.user_product_id:
                price_unit = move.workorder_id.user_price_unit
            if move.workorder_id and move.product_id == move.workorder_id.operation_id.material_product_id:
                price_unit = move.workorder_id.material_price_unit
            if move.product_id.type == 'consu' and price_unit == 0.0:
                price_unit = move.product_id.standard_price
                move.price_unit = price_unit
            company_from = move._is_out() and move.mapped('move_line_ids.location_id.company_id') or False
            company_to = move._is_in() and move.mapped('move_line_ids.location_dest_id.company_id') or False
            _logger.info("MOVE CREATE %s:%s:%s:%s" % (move._is_in(), move._is_out(), move.product_id.type, price_unit))
            if move.product_id.type == 'consu':
                if move._is_in():
                    amount = abs(price_unit * move.quantity_done)
                    journal_id, acc_src, acc_dest, acc_valuation = move._get_accounting_data_for_valuation()
                    move.with_context(force_company=company_to.id,
                                      force_valuation_amount=amount,
                                      forced_quantity=move.quantity_done)._create_account_move_line(acc_src,
                                                                                                    acc_valuation,
                                                                                                    journal_id)
                if move._is_out():
                    amount = -abs(price_unit * move.quantity_done)
                    journal_id, acc_src, acc_dest, acc_valuation = move._get_accounting_data_for_valuation()
                    move.with_context(force_company=company_from.id,
                                      force_valuation_amount=amount,
                                      forced_quantity=move.quantity_done)._create_account_move_line(acc_dest,
                                                                                                    acc_valuation,
                                                                                                    journal_id)

            if move.company_id.anglo_saxon_accounting:
                journal_id, acc_src, acc_dest, acc_valuation = move._get_accounting_data_for_valuation()
                if move._is_dropshipped():
                    move.with_context(force_company=move.company_id.id,
                                      force_valuation_amount=amount,
                                      forced_quantity=move.quantity_done)._create_account_move_line(acc_src, acc_dest,
                                                                                                    journal_id)
                elif move._is_dropshipped_returned():
                    move.with_context(force_company=move.company_id.id,
                                      force_valuation_amount=amount,
                                      forced_quantity=move.quantity_done)._create_account_move_line(acc_dest, acc_src,
                                                                                                    journal_id)
        return res

    def _run_valuation(self, quantity=None):
        value_to_return = super(StockMove, self)._run_valuation(quantity=quantity)
        if self.raw_material_production_id and self.raw_material_production_id.own_amount:
            self.own_value = self.raw_material_production_id.own_amount
        return value_to_return

    def _get_values_stock_move_line(self, finished_line, move_line_ids):
        product_id = self.raw_material_production_id.product_id
        final_move_id = self.raw_material_production_id.move_finished_ids
        qty = min(1, move_line_ids.qty_done)
        if product_id.tracking == 'serial':
            qty = 1.0
        else:
            coefficient = self.raw_material_production_id.product_qty / final_move_id.quantity_done
            qty = qty * coefficient

        return {
            'lot_id': move_line_ids.lot_id and move_line_ids.lot_id.id or False,
            'lot_produced_id': finished_line.lot_id.id,
            'ordered_qty': qty,
            'product_uom_qty': qty,
            'qty_done': qty,
            # 'move_id': self.id,
            'done_wo': True,
            # 'done_move': False,
            'product_id': move_line_ids.product_id.id,
            'product_uom_id': move_line_ids.product_uom_id.id,
            'location_id': move_line_ids.location_id.id,
            'location_dest_id': move_line_ids.location_dest_id.id,
            'state': 'assigned',
            'production_id': move_line_ids.production_id.id,
            'workorder_id': move_line_ids.workorder_id.id,
            # 'reference': self.raw_material_production_id.name,
        }

    @api.multi
    def action_populate_consumed_move_line(self):
        for record in self:
            # _logger.info("POPULATE %s" % record.raw_material_production_id.is_locked)
            if record.raw_material_production_id and not record.raw_material_production_id.is_locked:
                # child_manufacturing_orders = record.raw_material_production_id.child_production_order_ids.filtered(
                #     lambda mo: mo.product_id.id == record.product_id.id)
                # for child_order in record.raw_material_production_id.finished_move_line_ids:
                move_line_ids = self.raw_material_production_id.move_raw_ids.mapped('move_line_ids')
                if len(move_line_ids) > 1:
                    move_line_ids = move_line_ids[0]
                if not move_line_ids:
                    return False
                for inx, finished_line in enumerate(record.raw_material_production_id.finished_move_line_ids):
                    if not finished_line.qty_done:
                        continue
                    values = self.env['stock.move.line'].default_get([])
                    values.update(record._get_values_stock_move_line(finished_line, move_line_ids))
                    if not values:
                        continue
                    if inx == 0:
                        record.move_line_ids[0].lot_produced_id = finished_line.lot_id.id
                    else:
                        record.move_line_ids |= self.env['stock.move.line'].new(values)
                    # record.active_move_line_ids |= self.env['stock.move.line'].new(values)
                    # _logger.info("ADD RECORD %s" % values)
        return True


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    special_qty = fields.Float(
        string='Special Quantity',
        help='Quantity from other move in MRP work order.',
    )
    used_special_qty = fields.Float(
        string='Special Used Quantity',
        help='Used quantity from other move in MRP work order.',
    )
    progress = fields.Float(
        string='How many used',
        copy=False,
    )

    @api.onchange('lot_id')
    def _onchange_lot_id(self):
        for record in self:
            if record.workorder_id:
                production_id = record.workorder_id.production_id
                used_special_qty_ids = production_id.move_raw_ids. \
                    filtered(lambda r: r.product_id == record.product_id)
                special_qty = used_special_qty = 0.0
                for line in used_special_qty_ids.mapped('move_line_ids').filtered(lambda r: r.lot_id == record.lot_id):
                    special_qty += line.product_qty
                    used_special_qty += line.qty_done
                # _logger.info("SPECIAL QTY %s-%s:%s" % (used_special_qty_ids, special_qty, used_special_qty))
                if special_qty != 0.0:
                    record.special_qty = abs(special_qty)
                    record.used_special_qty = abs(used_special_qty)
                    record.progress = record.used_special_qty / record.special_qty * 100
                # _logger.info("UPDATED %s%s" % (record.special_qty, record.used_special_qty))

    @job
    @api.multi
    def mrp_rebuild_account_move(self):
        for record in self:
            record.with_context(dict(self._context, rebuld_try=True)).rebuild_account_move()

    @api.multi
    def write(self, vals):
        res = super(StockMoveLine, self).write(vals)
        if 'workorder_id' in vals and 'product_id' in vals:
            for record in self:
                record._onchange_lot_id()
                if record.product_id.type == 'consu':
                    record.workorder_id.user_price_unit = record.product_id.standard_price
        if 'qty_done' in vals:
            for record in self:
                production_id = record.move_id.raw_material_production_id
                if production_id and production_id.state == 'done' and not production_id.is_locked:
                    record.with_delay().mrp_rebuild_account_move()
        return res

    @api.model
    def create(self, vals):
        res = super(StockMoveLine, self).create(vals)
        if 'workorder_id' in vals and 'product_id' in vals:
            if res.product_id.type == 'consu':
                res.workorder_id.user_price_unit = res.product_id.standard_price
        return res
