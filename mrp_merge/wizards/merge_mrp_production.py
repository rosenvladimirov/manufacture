# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from itertools import groupby
from odoo import api, models, fields, _
# from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class MergeMrpProduction(models.TransientModel):
    _name = 'merge.mrp.production'
    _description = "Merge manufacture order wizard"

    @api.multi
    def action_merge_mrp_production(self):
        mrp_productions = self.env['mrp.production'].browse(self._context.get('active_ids'))
        mrp_production_ids = []
        product_old = mrp_production_id = move_finished = False
        for product, mrp_production in groupby(mrp_productions.sorted(lambda r: "%s-%s" % (r.product_id.id, r.bom_id.id)), lambda r: r.product_id):
            save_mrp_production = list(mrp_production)
            # _logger.info("NEW MOMP %s(%s)" % (product, save_mrp_production))
            # Check finished products and group by serial and add by lot
            for child_mrp_production in save_mrp_production:
                if product != product_old:
                    mrp_production_id = child_mrp_production.copy({
                        'product_qty': child_mrp_production.product_qty,
                    })
                    product_old = product
                    mrp_production_ids.append(mrp_production_id.id)
                    mrp_production_id.button_plan()
                    # mrp_production_id.move_raw_ids
                    move_finished = mrp_production_id.move_finished_ids.filtered(
                        lambda x: (x.product_id.id == mrp_production_id.product_id.id) and (
                                x.state not in ('done', 'cancel')))
                child_mrp_production.parent_production_order_id = mrp_production_id
                _logger.info("START WITH %s" % child_mrp_production)
                # Check for finished production
                for finish_product in child_mrp_production.move_finished_ids.sorted(lambda r: r.product_id.id):
                    move_line_finished = self.env['stock.move.line']
                    finish_product_unlink = self.env['stock.move']
                    _logger.info("CHECK PRODUCT MOVES %s" % finish_product)
                    # # Get operation from work order
                    operation_id = finish_product.workorder_id.operation_id
                    work_order_id = False
                    work_order_ids = mrp_production_id.mapped('workorder_ids')
                    # _logger.info("WO %s in (%s)" % (operation_id, work_order_ids.mapped('operation_id')))
                    if operation_id.id in work_order_ids.mapped('operation_id').ids:
                        for wo in work_order_ids:
                            if wo.operation_id == operation_id:
                                work_order_id = wo
                                break
                    for finish_move_line in finish_product.mapped('move_line_ids'):
                        # _logger.info("CHECK MOVE LINES %s" % finish_move_line)
                        if finish_move_line.qty_done > 0:
                            copy_move_line = finish_move_line.copy()
                            # copy_move_line.production_id = mrp_production_id
                            copy_move_line.workorder_id = work_order_id
                            copy_move_line.reference = finish_move_line.reference
                            copy_move_line.qty_done = finish_move_line.qty_done
                            # copy_move_line.product_qty = finish_move_line.product_qty
                            copy_move_line.qty_dome_merged = finish_move_line.qty_done
                            move_line_finished |= copy_move_line
                            finish_product_unlink |= finish_move_line.move_id
                    move_line_finished.write({
                        'move_id': move_finished.id,
                    })
                    # move_finished.quantity_done += sum([r.qty_done for r in move_line_finished])
                    _logger.info("FOR TRANSFERRED %s=%s" % (move_line_finished, sum([r.qty_done for r in move_line_finished])))
                    _logger.info("PACE FINAL FINISHED PRODUCT %s(%s)=%s" % (move_finished.move_line_ids, move_finished, move_finished.quantity_done))
                    # DEVELOP
                    # finish_product_unlink.mapped('move_line_ids').write({
                    #     'state': 'draft',
                    #     'qty_done': 0,
                    # })
                    # finish_product_unlink._action_cancel()
                # Check work orders consumations
                for wo in child_mrp_production.workorder_ids.sorted(lambda r: r.date_start and r.date_start or ''):
                    # Get operation from work order
                    operation_id = wo.operation_id
                    workorder_id = False # New work order for replacing
                    if operation_id.id in mrp_production_id.mapped('workorder_ids').mapped('operation_id').ids:
                        for work_order_id in mrp_production_id.mapped('workorder_ids'):
                            if work_order_id.operation_id == operation_id:
                                workorder_id = work_order_id
                                workorder_id.qty_produced += wo.qty_produced

                                workorder_id.date_planned_start = fields.Datetime.to_string(min(fields.Datetime.from_string(wo.date_planned_start), fields.Datetime.from_string(workorder_id.date_planned_start)))
                                workorder_id.date_planned_finished = fields.Datetime.to_string(max(fields.Datetime.from_string(wo.date_planned_finished), fields.Datetime.from_string(workorder_id.date_planned_finished)))

                                if workorder_id.date_start:
                                    workorder_id.date_start = fields.Datetime.to_string(min(fields.Datetime.from_string(wo.date_start), fields.Datetime.from_string(workorder_id.date_start)))
                                else:
                                    workorder_id.date_start = wo.date_start
                                if workorder_id.date_finished and wo.date_finished:
                                    workorder_id.date_finished = fields.Datetime.to_string(max(fields.Datetime.from_string(wo.date_finished), fields.Datetime.from_string(workorder_id.date_finished)))
                                else:
                                    workorder_id.date_finished = wo.date_finished
                                if workorder_id.production_date:
                                    workorder_id.production_date = fields.Datetime.to_string(min(fields.Datetime.from_string(wo.production_date), fields.Datetime.from_string(workorder_id.production_date)))
                                else:
                                    workorder_id.production_date = wo.production_date
                                break
                    move_raw_lines = self.env['stock.move']
                    for move_raw_line in wo.move_raw_ids:
                        move_line_lines = self.env['stock.move.line']
                        copy_move_raw_line = move_raw_line.copy()
                        copy_move_raw_line.workorder_id = workorder_id
                        copy_move_raw_line.raw_material_production_id = mrp_production_id
                        # copy_move_raw_line.production_id = mrp_production_id
                        move_raw_lines |= copy_move_raw_line
                        # move_component_lines = self.env['stock.move.line']
                        for move_line in move_raw_line.move_line_ids.filtered(lambda r: r.done_wo):
                            copy_move_line = move_line.copy()
                            copy_move_line.qty_done = move_line.qty_done
                            # copy_move_line.product_qty = move_line.product_qty
                            copy_move_line.reference = move_line.reference
                            copy_move_line.workorder_id = workorder_id
                            copy_move_line.production_id = mrp_production_id
                            # copy_move_line.move_id = copy_move_raw_line
                            move_line_lines |= copy_move_line
                            move_line.qty_dome_merged = move_line.qty_done
                            update_values = workorder_id._update_production_datails(copy_move_line)
                            if update_values:
                                mrp_production_id.production_line_ids = update_values
                            # DEVELOP
                            # move_line.state = 'draft'
                            # move_line.qty_done = 0
                        move_line_lines.write({
                            'move_id': copy_move_raw_line.id,
                        })
                        try:
                            # - lubo - move_raw_line.quantity_done = 0
                            move_raw_line.state = 'new'
                            move_raw_line.do_unreserve()
                            move_raw_line._action_cancel()
                        except ValueError:
                            _logger.info("Cannot cancel the stock moves %s" % move_raw_line.name)
                    for time in wo.time_ids:
                        time = time.copy()
                        time.workorder_id = workorder_id

                    workorder_id._compute_duration()

                    # scrap_lines = self.env['stock.scrap']
                    # !!! To resolve
                    for scrap_line in wo.scrap_ids:
                        copy_scrap_line = scrap_line.copy()
                        copy_scrap_line.workorder_id = workorder_id
                        copy_scrap_line.production_id = mrp_production_id

            # mrp_production_id.move_finished_ids = move_finished
            mrp_production_id.product_qty = sum([r.quantity_done for r in move_finished])
            if len(mrp_production_id.workorder_ids.ids):
                mrp_production_id.finished_move_line_ids.filtered(lambda r: not r.workorder_id).write({
                    'workorder_id': mrp_production_id.workorder_ids[-1].id
                })
            mrp_production_id.state = 'progress'
            mrp_production_id.origin = ",".join([x.name for x in save_mrp_production])
            mrp_production_id.workorder_ids.write({
                'qty_production': mrp_production_id.product_qty,
                'state': 'done',
            })

        return {
            'name': _('Opened new Manufacture orders'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'mrp.production',
            'search_view_id': self.env.ref('mrp.view_mrp_production_filter').id,
            'context': {'search_default_todo': True},
            'domain': [('id', 'in', mrp_production_ids)],
        }
