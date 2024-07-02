# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

import logging

_logger = logging.getLogger(__name__)


class ChangeProductionQty(models.TransientModel):
    _inherit = 'change.production.qty'

    update_base_new_bom = fields.Boolean('Update consumption from new BOM')

    @api.multi
    def change_prod_qty(self):
        for wizard in self:
            production = wizard.mo_id
            if wizard.update_base_new_bom:
                # if len(production.workorder_ids.ids) > 0:
                #     raise UserError(_("You have already processed WO."))
                if len(production.move_raw_ids.filtered(lambda r: r.state == 'done').ids) > 0:
                    continue
                for moves_to_unlink in production.move_raw_ids.filtered(lambda r: r.state not in ('done', 'cancel')):
                    _logger.info("MOVE UNLINK %s:%s" % (moves_to_unlink, production.move_raw_ids.ids))
                    moves_to_unlink._do_unreserve()
                    moves_to_unlink._action_cancel()
                    moves_to_unlink.sudo().unlink()

                if len(production.move_raw_ids.ids) == 0:
                    factor = production.product_uom_id.\
                                 _compute_quantity(production.product_qty,
                                                   production.bom_id.product_uom_id) / production.bom_id.product_qty
                    boms, lines = production.bom_id.explode(production.product_id, factor,
                                                            picking_type=production.bom_id.picking_type_id)
                    production._generate_raw_moves(lines)
                    # Check for all draft moves whether they are mto or not
                    production._adjust_procure_method()
                    production.move_raw_ids._action_confirm()
                if len(production.workorder_ids.ids) > 0:
                    for wo in production.workorder_ids:
                        moves_raw = production.move_raw_ids.filtered(lambda move: move.operation_id == wo.operation_id)
                        if len(production.workorder_ids) == len(production.routing_id.operation_ids):
                            moves_raw |= production.move_raw_ids.filtered(lambda move: not move.operation_id)
                        moves_finished = production.move_finished_ids.filtered(lambda move: move.operation_id == wo.operation_id) #TODO: code does nothing, unless maybe by_products?
                        moves_raw.mapped('move_line_ids').write({'workorder_id': wo.id})
                        (moves_finished + moves_raw).write({'workorder_id': wo.id})

            if wizard.product_qty != production.product_qty:
                produced = production.qty_produced
                rest_production_qty = produced == 0.0 and 1.0 or produced
                produced = produced == 0.0 and 1.0 or produced
                production.progress = rest_production_qty / produced * 100

            rest_production_qty = wizard.product_qty - production.qty_produced
            if float_compare(rest_production_qty, 0.0, precision_rounding=production.product_uom_id.rounding) == 0:
                for wo in production.workorder_ids.\
                        filtered(lambda r: r.state == 'progress' and r.qty_produced == wizard.product_qty):
                    for timeline in wo.time_ids:
                        timeline.write({'date_end': fields.Datetime.now()})
        return super(ChangeProductionQty, self).change_prod_qty()
