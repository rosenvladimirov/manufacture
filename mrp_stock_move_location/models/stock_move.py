# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from itertools import groupby
from odoo.exceptions import UserError, RedirectWarning
from odoo.tools import float_is_zero
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    production_ids = fields.Many2many(
        comodel_name='mrp.production',
        relation='mrp_production_stock_move_rel',
        column1='stock_move_id',
        column2='mrp_production_id',
        string='Productions',
    )

    def _update_reserved_quantity(self, need, available_quantity, location_id, lot_id=None, package_id=None,
                                  owner_id=None, strict=True):
        # _logger.info("UPDATE RESERVATION %s:%s:%s:%s::%s(%s)" % (
        #     self.product_id.display_name, need, available_quantity, location_id, lot_id, self._context))
        if not self._context.get('force_pass') \
                and (self.raw_material_production_id and self._context.get('force_pass_picking')):
            production_id = self.raw_material_production_id
            move_raw_ids = production_id.move_raw_ids.filtered(lambda r: r.product_id == self.product_id)
            used_lots = move_raw_ids.mapped('move_line_ids').mapped('lot_id')
            stock_move_lines_ids = production_id.stock_move_lines_ids. \
                filtered(lambda r: r.product_id == self.product_id and r.lot_id.id not in used_lots.ids). \
                sorted(lambda r: "%s-%s" % (r.product_id.id, r.lot_id.name))
            taken_quantity = 0.0
            need_current = self.product_uom_qty
            for line in stock_move_lines_ids:
                need_current_line = need_current - taken_quantity
                if need_current_line > line.qty_done:
                    need_current_line = line.qty_done
                available_quantity_new = self.env['stock.quant']._get_available_quantity(
                    line.product_id, line.location_dest_id, lot_id=line.lot_id, owner_id=line.owner_id, strict=True)
                taken_quantity += self.with_context(dict(self._context, force_pass=True))._update_reserved_quantity(
                    need_current_line, available_quantity_new,
                    line.location_dest_id,
                    lot_id=line.lot_id,
                    package_id=line.package_id,
                    owner_id=line.owner_id, strict=True)
                if taken_quantity > 0:
                    used_lots |= line.lot_id
            need -= taken_quantity
            if float_is_zero(need, precision_rounding=self.product_id.uom_id.rounding) or need < 0:
                return 0.0
            # if self._context.get('force_pass_picking'):
            #     return 0.0
        return super(StockMove, self)._update_reserved_quantity(need, available_quantity, location_id, lot_id=lot_id,
                                                                package_id=package_id, owner_id=owner_id, strict=strict)

    def _action_assign(self):
        # manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        for move in self.filtered(lambda m: m.state in ['assigned', 'confirmed', 'waiting', 'partially_available']):
            production_id = move.raw_material_production_id
            if production_id and production_id.stock_move_lines_ids.\
                    filtered(lambda r: r.product_id == move.product_id and r.state == 'done'):
                move_raw_ids = production_id.move_raw_ids.filtered(lambda r: r.product_id == move.product_id)
                if move.id in move_raw_ids.ids and move._context.get('force_pass'):
                    continue

                if move.id in move_raw_ids.ids \
                        and move.state == 'assigned' \
                        and move.product_uom_qty - move.reserved_availability != 0:
                    if move.product_uom_qty - move.reserved_availability > 0:
                        move.state = 'partially_available'
                    if move.reserved_availability == 0:
                        move.state = 'confirmed'
                    # _logger.info("MOVE FORWARD TO ASSIGN %s:%s:%s" % (
                    #     move.product_id.display_name, move.product_uom_qty - move.reserved_availability, move.state))
            super(StockMove, move)._action_assign()

    @api.model
    def create(self, vals):
        production_ids = False
        if 'production_ids' in vals and 'group_id' in vals:
            procurement_id = self.env['procurement.group'].browse(vals['group_id'])
            if len(procurement_id.production_ids.ids) > 0:
                production_ids = vals['production_ids']
                vals.pop('production_ids')
        res = super(StockMove, self).create(vals)
        if production_ids and res:
            res.write({
                "production_ids": production_ids,
            })
            _logger.info("RES and VALS %s:%s" % (res, vals))
        return res


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    production_ids = fields.Many2many(
        comodel_name='mrp.production',
        relation='mrp_production_stock_move_line_rel',
        column1='stock_move_line_id',
        column2='mrp_production_id',
        string='Productions',
    )

    @api.model
    def create(self, vals):
        # _logger.info("VALS CREATE %s" % vals)
        if 'move_id' in vals:
            move = self.env['stock.move'].browse(vals['move_id'])
            if move.production_ids:
                vals['production_ids'] = [(6, False, move.production_ids.ids)]
        return super(StockMoveLine, self).create(vals)

    # @api.multi
    # def write(self, vals):
    #     for record in self:
    #         # _logger.info("VALS WRITE %s" % vals)
    #         if record.move_id and record.move_id.production_ids and not record.production_ids:
    #             vals['production_ids'] = [(6, False, record.move_id.production_ids.ids)]
    #     return super(StockMoveLine, self).write(vals)


class ProcurementGroup(models.Model):
    _inherit = 'procurement.group'

    production_ids = fields.Many2many('mrp.production', string='Mrp Production')
    location_dest_id = fields.Many2one('stock.location', 'Destination Location')


class ProcurementRule(models.Model):
    _inherit = 'procurement.rule'

    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_id, name, origin, values, group_id):
        result = super(ProcurementRule, self)._get_stock_move_values(product_id, product_qty, product_uom, location_id, name, origin, values, group_id)
        _logger.info("GROUP %s" % group_id)
        group = self.env['procurement.group'].browse(group_id)
        if group.location_dest_id:
            result['location_dest_id'] = group.location_dest_id.id
        if len(group.production_ids.ids) > 0:
            result['production_ids'] = [(6, False, group.production_ids.ids)]
        _logger.info("RESULT and VALUES %s:%s" % (result, values))
        return result
