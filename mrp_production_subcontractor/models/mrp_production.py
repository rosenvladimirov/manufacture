# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    extra_product_ids = fields.Many2many('product.product', string='Added extra cost')

    @api.multi
    def _account_entry_move(self):
        self.ensure_one()
        if self.state == 'done':
            final_moves = self.move_finished_ids.filtered(lambda x: x.state == 'done')
        else:
            final_moves = self.move_finished_ids.filtered(
                lambda x: (x.product_id.id == self.product_id.id) and (x.state not in ('done', 'cancel')))
        if len(final_moves.ids) > 1:
            final_moves = final_moves[0]
        if self.state != 'cancel' and len(final_moves.ids) > 0:
            for product_id in self.extra_product_ids:
                if product_id.property_subcontracted_service:
                    accounts_data = product_id.product_tmpl_id.get_product_accounts()
                    acc_src = accounts_data['expense'].id

                    final_accounts_data = self.product_id.product_tmpl_id.get_product_accounts()
                    if final_moves.location_id.valuation_out_account_id:
                        acc_dest = final_moves.location_id.valuation_out_account_id.id
                    else:
                        acc_dest = final_accounts_data['stock_input'].id
                    if not accounts_data.get('stock_journal', False):
                        raise UserError(_('You don\'t have any stock journal defined on your product category, check if you have installed a chart of accounts'))
                    if not acc_src:
                        raise UserError(_('Cannot find a stock input account for the product %s. You must define one on the product category, or on the location, before processing this operation.') % (self.product_id.display_name))
                    if not acc_dest:
                        raise UserError(_('Cannot find a stock output account for the product %s. You must define one on the product category, or on the location, before processing this operation.') % (self.product_id.display_name))
                    journal_id = accounts_data['stock_journal'].id
                    debit_line_vals = {
                        'name': self.name,
                        'product_id': product_id.id,
                        'quantity': 1.0,
                        'product_uom_id': product_id.uom_id.id,
                        'ref': self.name,
                        'debit': self.service_amount,
                        'credit': 0,
                        'production_id': self.id,
                        'account_id': acc_dest,
                        'analytic_account_id': self.analytic_account_id.id,
                    }
                    credit_line_vals = {
                        'name': self.name,
                        'product_id': product_id.id,
                        'quantity': 1.0,
                        'product_uom_id': product_id.uom_id.id,
                        'ref': self.name,
                        'credit': self.service_amount,
                        'debit': 0,
                        'production_id': self.id,
                        'account_id': acc_src,
                        'analytic_account_id': self.analytic_account_id.id,
                    }
                    res = [(0, 0, debit_line_vals), (0, 0, credit_line_vals)]
                    # _logger.info('RES %s' % res)
                    if res:
                        new_account_move = self.env['account.move'].sudo().create({
                            'journal_id': journal_id,
                            'line_ids': res,
                            'date': final_moves.accounting_date or final_moves.date,
                            'ref': self.name,
                            'production_id': self.id,
                        })
                        new_account_move.post()

    @api.depends('move_raw_ids.quantity_done', 'move_raw_ids.product_qty')
    def _compute_service_amount(self):
        res = super(MrpProduction, self)._compute_service_amount()
        for production in self:
            if len(production.extra_product_ids.ids) > 0:
                service_amount = production.service_amount
                for product_id in production.extra_product_ids:
                    price_subtotal = product_qty = 0.0
                    if product_id.type == 'service' and product_id.property_subcontracted_service:
                        orders = self.env['purchase.order'].search(
                            [('group_id', '=', production.procurement_group_id.id)])
                        for order in orders:
                            for order_line in order.order_line:
                                if order_line.product_id == product_id:
                                    price_subtotal += order_line.price_subtotal
                                    product_qty += order_line.product_qty
                                # _logger.info("PURCHASE LINE %s = %s * %s = %s" % (
                                # order_line, (price_subtotal / product_qty), production.qty_produced, (price_subtotal / product_qty) * production.qty_produced))
                            service_amount += (price_subtotal/product_qty) * production.qty_produced

                        if not orders:
                            service_amount += product_id.standard_price * production.qty_produced
                    production.service_amount = abs(service_amount)
        return res

    @api.multi
    def check_service_invoiced(self):
        res = super(MrpProduction, self).check_service_invoiced()
        for production in self:
            if len(production.extra_product_ids.ids) > 0:
                service_amount = production.service_amount
                for product_id in production.extra_product_ids:
                    if product_id.type == 'service' and product_id.property_subcontracted_service:
                        orders = self.env['purchase.order'].search(
                            [('group_id', '=', production.procurement_group_id.id)])
                        for order in orders:
                            if order.invoice_status != 'invoiced':
                                raise UserError(_('Order %s is not invoiced') % order.name)
                            for invoice in order.invoice_ids:
                                if not invoice.move_id:
                                    raise UserError(_('Invoice %s is not validated') % invoice.number)
                                else:
                                    for acc_move_line in invoice.move_id.line_ids:
                                        acc_move_line.write({'production_id': production.id})
                                        if acc_move_line.product_id and acc_move_line.product_id == product_id:
                                            service_amount += acc_move_line.debit + acc_move_line.credit
                production.write({'service_amount': abs(service_amount)})
        return res

    @api.multi
    def unlink(self):
        subcontractor_id = self.env['mrp.production.ordered.subcontractor'].search([
            ('production_id', 'in', self.ids)
        ])
        if subcontractor_id:
            subcontractor_id.unlink()
        return super(MrpProduction, self).unlink()
