# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
import math

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    amount = fields.Float(digits=dp.get_precision('Account'), string='Production Amount',
                          compute='_calculate_amount')
    calculate_price = fields.Float(digits=dp.get_precision('Account'), string='Calculate Price',
                                   compute='_calculate_amount')
    service_amount = fields.Float(digits=dp.get_precision('Account'), string='Service Amount',
                                  compute='_compute_service_amount',
                                  inverse='_set_service_amount', store=True)
    overhead_amount = fields.Float(string='Overhead', help="For Value Overhead percent enter % ratio between 0-1.",
                                   compute='_calculate_amount',
                                   default='0.0')
    acc_move_line_ids = fields.One2many('account.move.line', 'production_id', string='Account move lines')


    @api.depends('move_raw_ids.quantity_done', 'move_raw_ids.product_qty')
    def _compute_service_amount(self):
        for production in self:
            service_amount = 0.0
            for move in production.move_raw_ids:
                if move.product_id.type != 'product':
                    qty = move.quantity_done or move.product_qty
                    service_amount += move.price_unit * qty
            production.service_amount = service_amount

    def _set_service_amount(self):
        service_amount = self.service_amount
        service_product = self.env['product.product']
        for move in self.move_raw_ids:
            if move.product_id.type != 'product':
                service_product |= move.product_id
                qty = move.quantity_done or move.product_qty
        if len(service_product) == 1 and qty:
            price = service_amount / qty
            service_product.write({'standard_price': price})

    @api.multi
    def _calculate_amount(self):
        for production in self:
            calculate_price = 0.0
            amount = 0.0
            service_amount = 0.0
            planned_cost = True
            for move in production.move_raw_ids:
                if move.quantity_done > 0:
                    planned_cost = False  # nu au fost facute miscari de stoc

            if planned_cost:
                for move in production.move_raw_ids:
                    if move.product_id.type == 'product':
                        qty = move.product_qty + move.product_qty * move.product_id.scrap
                        if move.product_uom_id != move.product_id.uom_id:
                            qty = move.product_uom_id._compute_quantity(move.product_qty, move.product_id.uom_id)
                            qty = qty * move.product_id.scrap
                        amount += move.price_unit * qty
                product_qty = production.product_qty
            else:
                for move in production.move_raw_ids:
                    if move.product_id.type == 'product':
                        qty = move.quantity_done
                        if move.product_uom_id != move.product_id.uom_id:
                            qty = move.product_uom_id._compute_quantity(move.quantity_done, move.product_id.uom_id)
                        amount += abs(move.price_unit) * qty
                product_qty = 0.0
                for move in production.move_finished_ids:
                    product_qty += move.quantity_done
                if product_qty == 0.0:
                    product_qty = production.product_qty

            if production.routing_id:
                for operation in production.routing_id.operation_ids:
                    time_cycle = operation.get_time_cycle(quantity=product_qty, product=production.product_id)

                    cycle_number = math.ceil(product_qty / operation.workcenter_id.capacity)
                    duration_expected = (operation.workcenter_id.time_start +
                                         operation.workcenter_id.time_stop +
                                         cycle_number * time_cycle * 100.0 / operation.workcenter_id.time_efficiency)

                    amount += (duration_expected / 60) * operation.workcenter_id.costs_hour

            amount += production.service_amount
            calculate_price = amount / product_qty
            production.calculate_price = calculate_price
            production.amount = amount

    def _cal_price(self, consumed_moves):
        super(MrpProduction, self)._cal_price(consumed_moves)
        self.ensure_one()
        production = self
        self._calculate_amount()  # refac calculul
        price_unit = production.calculate_price
        self.move_finished_ids.write({'price_unit': price_unit})
        # functia standard nu permite si de aceea am facut o modificare in deltatech_purchase_price
        self.move_finished_ids.product_price_update_before_done()
        return True

    @api.multi
    def check_service_invoiced(self):
        for production in self:
            service_amount = 0
            for line in production.bom_id.bom_line_ids:
                if line.product_id.type == 'service':
                    # care este comanda de achizitie ?
                    orders = self.env['purchase.order'].search([('group_id', '=', production.procurement_group_id.id)])
                    for order in orders:
                        if order.invoice_status != 'invoiced':
                            raise UserError(_('Order %s is not invoiced') % order.name)
                        for invoice in order.invoice_ids:
                            if not invoice.move_id:
                                raise UserError(_('Invoice %s is not validated') % invoice.number)
                            else:
                                for acc_move_line in invoice.move_id.line_ids:
                                    acc_move_line.write({'production_id': production.id})
                                    if acc_move_line.product_id:
                                        service_amount += acc_move_line.debit + acc_move_line.credit
            if service_amount:
                production.write({'service_amount': service_amount})

    @api.multi
    def post_inventory(self):
        self.check_service_invoiced()
        res = super(MrpProduction, self).post_inventory()
        for production in self:
            acc_move_line_ids = self.env['account.move.line']
            for move in production.move_raw_ids:
                acc_move_line_ids |= move.account_move_ids.line_ids
            for move in production.move_finished_ids:
                acc_move_line_ids |= move.account_move_ids.line_ids
            if acc_move_line_ids:
                acc_move_line_ids.write({'production_id': production.id})
        return res
