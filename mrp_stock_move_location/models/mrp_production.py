# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    stock_move_lines_ids = fields.Many2many(
        comodel_name='stock.move.line',
        relation='mrp_production_stock_move_line_rel',
        column1='mrp_production_id',
        column2='stock_move_line_id',
        string='Stock moves',
        copy=False,
    )

    picking_move_ids = fields.Many2many(
        comodel_name='stock.picking',
        relation='mrp_production_stock_picking_rel',
        column1='mrp_production_id',
        column2='stock_picking_id',
        string='Pickings',
        copy=False,
    )

    try_reservation = fields.Boolean(
        string='Try reservation',
        compute='_compute_try_reservation',
        store=True
    )

    @api.depends('move_raw_ids.reserved_availability')
    @api.multi
    def _compute_try_reservation(self):
        for record in self:
            if record.state not in ('done', 'cancel'):
                record.try_reservation = not any([x for x in record.move_raw_ids.mapped('move_line_ids')])
            else:
                record.try_reservation = False

    @api.multi
    def action_auto_fix_lots(self):
        for record in self:
            if record.check_to_done:
                for line in record.move_raw_ids.filtered(lambda r: r.has_tracking):
                    assign_id = self.env['assign.manual.quants'].\
                        with_context(dict(self._context, sale_move_ids=line.id)).create({})
                    for quants in assign_id.quants_lines.filtered(lambda r: r.on_hand - r.reserved != 0.0):
                        if not quants.lot_id:
                            quants.selected = False
                            quants._onchange_selected()
                        if assign_id.move_qty > 0.0 and quants.lot_id:
                            _logger.info("PRODUCT PASSING %s" % line.product_id.display_name)
                            try:
                                quants.selected = True
                                quants._onchange_selected()
                            except ValueError:
                                _logger.info(_('Error when select quantity %s' % record.product_id.display_name))
                    if line.product_uom_qty > assign_id.move_qty >= 0.0:
                        assign_id.assign_quants()
