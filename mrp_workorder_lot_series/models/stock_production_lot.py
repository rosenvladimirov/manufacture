#  -*- coding: utf-8 -*-
#  Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, exceptions, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockProductionLot(models.Model):
    _inherit = 'stock.production.lot'

    @api.multi
    def update_lot_ref(self, product_check_id):
        for record in self:
            if record.ref:
                lot_id = self.env['stock.production.lot'].search([('product_id', '=', product_check_id),
                                                                  ('ref', '=', record.ref)])
                _logger.info("SEARCH %s" % record.ref)
                if lot_id:
                    check_lot_id = self.env['stock.production.lot'].search(
                        [('product_id', '=', record.product_id.id), ('name', '=', lot_id.name)])
                    # log("TEST LOT %s:%s:%s:%s" % (rec.ref, rec.name, lot_id.name, check_lot_id.name), level='info')
                    _logger.info("TEST LOT %s:%s:%s:%s" % (record.ref, record.name, lot_id.name, check_lot_id.name))

                    if not check_lot_id:
                        record.name = lot_id.name

                    # if not check_lot_id.ref:
                    #     move_line_ids = self.env['stock.move.line'].search([('lot_id', '=', check_lot_id.id)])
                    #     move_line_ids.write({'lot_id': record.id})
                    #     # check_lot_id.ref = lot_id.ref

    @api.multi
    def _update_product_populate_ids(self, vals, force_update=False):
        for record in self:
            product = record.product_id
            if product.use_ref and not record.ref:
                record.ref = record.name

            if product.product_populate_ids:
                for product in product.product_populate_ids:
                    domain = False
                    ref = vals.get('ref') or record.ref
                    name = vals.get('name') or record.name
                    if not force_update:
                        domain = [('product_id', '=', product.product_populate_id.id)]
                        domain.append(('name', '=', name))
                        if ref:
                            domain.append(('ref', '=', ref))
                    elif product.product_populate_id.use_ref:
                        domain = [('product_id', '=', product.product_populate_id.id),
                                  ('name', '=', ref)]

                    if domain:
                        lot_id = self.env['stock.production.lot'].search(domain, limit=1)
                        if lot_id:
                            if lot_id.name != name:
                                lot_id.name = name
                            if lot_id.ref != record.ref:
                                lot_id.ref = ref
                        elif not force_update and product.product_populate_id.use_ref and not lot_id:
                            record._update_product_populate_ids(vals, force_update=True)
                        else:
                            self.env['stock.production.lot'].create({
                                'product_id': product.product_populate_id.id,
                                'name': name,
                                'ref': ref,
                            })

    @api.model
    def create(self, vals):
        res = super().create(vals)
        if vals.get('product_id'):
            res._update_product_populate_ids(vals)
        return res

    @api.multi
    def write(self, vals):
        res = super().write(vals)
        if vals.get('name') or vals.get('ref'):
            self._update_product_populate_ids(vals)
        return res
