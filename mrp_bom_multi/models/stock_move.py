# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class StockMove(models.Model):
    _inherit = "stock.move"

    def _prepare_procurement_values(self):
        res = super(StockMove, self)._prepare_procurement_values()
        if self.sale_line_id:
            res.update({
                'sale_line_id': self.sale_line_id and self.sale_line_id.id or False,
                'user_id': self.sale_line_id.order_id.user_id and self.sale_line_id.order_id.user_id.id or False,
            })
        return res
