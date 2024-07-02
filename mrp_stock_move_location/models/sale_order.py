# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from itertools import groupby
from odoo.exceptions import UserError, RedirectWarning
from odoo.tools import float_is_zero
import logging

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.multi
    def _prepare_procurement_values(self, group_id=False):
        values = super(SaleOrderLine, self)._prepare_procurement_values(group_id=group_id)
        # _logger.info("GROUP %s" % group_id)
        if len(group_id.production_ids.ids) > 0:
            values.update({
                'production_ids': [(6, False, group_id.production_ids.ids)]
            })
        return values

    @api.multi
    def _get_delivered_qty(self):
        self.ensure_one()
        if self.order_id.procurement_group_id and len(self.order_id.procurement_group_id.production_ids.ids) > 0:
            production_ids = self.order_id.procurement_group_id.production_ids
            delivered_qty = 0.0
            for production_id in production_ids:
                for move_id in production_id.move_raw_ids.\
                        filtered(lambda r: r.is_done and r.product_id == self.product_id):
                    delivered_qty += move_id.quantity_done
            return delivered_qty
        return super(SaleOrderLine, self)._get_delivered_qty()

    @api.depends('invoice_lines.invoice_id.state', 'invoice_lines.quantity')
    def _get_invoice_qty(self):
        super(SaleOrderLine, self)._get_invoice_qty()
        for record in self:
            if record.order_id.procurement_group_id and len(record.order_id.procurement_group_id.production_ids.ids) > 0:
                production_ids = record.order_id.procurement_group_id.production_ids
                for production_id in production_ids:
                    for move_id in production_id.move_raw_ids. \
                            filtered(lambda r: r.is_done and r.product_id == record.product_id):
                        record.qty_invoiced += move_id.quantity_done
