# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models, fields, api, _

import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    mrp_production_ids = fields.Many2many('mrp.production', string='Production orders')
    alternative_stock_move_ids = fields.One2many('mrp.workorder.trusted.lots', inverse_name='workorder_id',
                                                 string='Trusted lots')

    @api.onchange('mrp_production_ids')
    def onchange_mrp_production_ids(self):
        for record in self:
            record.alternative_stock_move_ids = False
            used_alternative_stock_move_ids = set([])
            alternative_stock_move_ids = []
            if len(record.mrp_production_ids.ids) > 0:
                move_line_ids = record.mapped('mrp_production_ids').filtered(lambda r: r != record.production_id).mapped('finished_move_line_ids')
                for line in move_line_ids:
                    if line.product_id == record.product_id and line.lot_id.name not in used_alternative_stock_move_ids:
                        alternative_stock_move_ids.append((0, False, {
                            'production_id': line.move_id.raw_material_production_id.id,
                            'product_id': line.product_id.id,
                            'lot_id': line.lot_id.id,
                            'name': line.lot_id.name,
                            'ref': line.lot_id.ref,
                        }))
                        used_alternative_stock_move_ids.update([line.lot_produced_id.name])

                move_line_ids = record.mapped('mrp_production_ids').mapped('move_raw_ids').\
                    mapped('move_line_ids').filtered(lambda r: r.lot_produced_id)
                for line in move_line_ids:
                    if line.workorder_id and line.lot_produced_id.name not in used_alternative_stock_move_ids:
                        alternative_stock_move_ids.append((0, False, {
                            'workorder_id': line.workorder_id.id,
                            'production_id': line.workorder_id.production_id.id,
                            'product_id': line.workorder_id.product_id.id,
                            'lot_id': line.lot_produced_id.id,
                            'name': line.lot_produced_id.name,
                            'ref': line.lot_produced_id.ref,
                        }))
                        used_alternative_stock_move_ids.update([line.lot_produced_id.name])

                record.alternative_stock_move_ids = alternative_stock_move_ids

    def _check_product(self, product, qty=1.0, lot=False, code=False, use_date=False):
        if self.product_id.tracking != 'none' and len(self.alternative_stock_move_ids.ids) > 0:
            code = code or ''
            lot = lot or ''
            if not self.alternative_stock_move_ids.filtered(
                    lambda r: r.name == lot or r.ref == code):
                raise UserError(_('This lot %s is prohibited for use in this order') % lot)
        return super(MrpWorkorder, self)._check_product(product, qty=qty, lot=lot, code=code, use_date=use_date)


class MrpProductionTrustedLots(models.Model):
    _name = 'mrp.workorder.trusted.lots'
    _description = 'Trusted Lots'

    workorder_id = fields.Many2one('mrp.workorder', string='Workorder', index=True, ondelete='cascade')
    production_id = fields.Many2one('mrp.production', string='Production')
    product_id = fields.Many2one('product.product', string='Product')
    lot_id = fields.Many2one('stock.production.lot', string='Lot/SN')
    name = fields.Char(string='Lot/SN Name')
    ref = fields.Char(string='Reference')
