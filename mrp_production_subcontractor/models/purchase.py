# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models, _



class ProcurementRule(models.Model):
    _inherit = 'procurement.rule'

    def _prepare_purchase_order(self, product_id, product_qty, product_uom, origin, values, partner):
        if 'force_partner_id' in values:
            partner = values['force_partner_id']
        return super(ProcurementRule, self).\
            _prepare_purchase_order(product_id, product_qty, product_uom, origin, values, partner)

    @api.multi
    def _prepare_purchase_order_line(self, product_id, product_qty, product_uom, values, po, supplier):
        res = super(ProcurementRule, self).\
            _prepare_purchase_order_line(product_id, product_qty, product_uom, values, po, supplier)
        if 'note2' in values and values.get('subcontractor', False):
            if po.note2:
                res['note2'] = po.note2 + '<br/>' + values['note2']
            else:
                res['note2'] = values['note2']
        return res
