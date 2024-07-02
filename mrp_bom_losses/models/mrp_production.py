# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
import math
from itertools import groupby
from statistics import mean

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
from odoo.addons.mrp.models.mrp_production import MrpProduction as mrpproduction
from odoo.addons.queue_job.job import job

import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    raw_move_line_ids = fields.One2many('stock.move.line', compute='_compute_raw_move_lines',
                                        inverse='_inverse_raw_move_lines', string="Raw Materials Detail operations")
    move_consumed_ids = fields.One2many('stock.move', compute='_compute_consumed_move', string="Consumed components")
    location_virtual_id = fields.Many2one('stock.location', 'Finished Products Location',
                                          default=lambda
                                              self: self.product_id and self.product_id.property_stock_production.id,
                                          readonly=True,
                                          help="Location where the system will produced the product.")
    amount = fields.Float(digits=dp.get_precision('Account'), string='Production Amount')
    calculate_price = fields.Float(string='Calculate Price')
    service_amount = fields.Float(digits=dp.get_precision('Account'), string='Service Amount',
                                  compute='_compute_service_amount',
                                  inverse='_set_service_amount', store=True)
    overhead_amount = fields.Float(string='Overhead', help="For Value Overhead percent enter % ratio between 0-1.",
                                   default='0.0')
    own_amount = fields.Float(digits=dp.get_precision('Account'), string='Own Materials Amount')
    own_calculate_price = fields.Float(string='Own Calculate Price')
    analytic_account_id = fields.Many2one('account.analytic.account', string="Analytic Account")
    acc_move_line_ids = fields.One2many('account.move.line', 'production_id', string='Account move lines')
    has_account_move = fields.Boolean(compute="_compute_has_account_move")
    reserved_lot_ids = fields.One2many('stock.production.lot', compute="_compute_reserved_lot_ids")
    sub_production = fields.Selection([
        ('normal', 'Only current MO'),
        ('sub', 'All Sub level'),
    ], string="Sub production level", copy=True, required=True, default='normal',
        help="Please select manufacture order level before save."
             "* Only current MO. Use normal to create only current manufacture order.\n"
             "* All Sub level. Create all Sub level manufacture order.\n")
    sub_production_toggle = fields.Boolean('Toggle sub production', compute='_compute_sub_production')
    progress = fields.Float(string='How many produced', copy=False)

    @api.depends('acc_move_line_ids', 'state')
    def _compute_has_account_move(self):
        for move in self:
            move.has_account_move = (move.state != 'done') or (
                    move.state == 'done' and len(move.acc_move_line_ids.ids) == 0)

    @api.depends('move_raw_ids.move_line_ids')
    def _compute_raw_move_lines(self):
        for production in self:
            production.raw_move_line_ids = production.move_raw_ids.mapped('move_line_ids')

    @api.multi
    def _compute_sub_production(self):
        for record in self:
            if record.sub_production == 'sub':
                record.sub_production_toggle = True
            else:
                record.sub_production_toggle = False

    @api.depends('sub_production')
    @api.multi
    def toggle_sub_production(self):
        for record in self:
            toggle = {'normal': 'sub', 'sub': 'normal'}
            record.sub_production = toggle[record.sub_production]

    @api.onchange('sub_production_toggle')
    @api.depends('sub_production')
    def _onchange_sub_production_toggle(self):
        for record in self:
            record.toggle_sub_production()
            record._compute_sub_production()

    def _inverse_raw_move_lines(self):
        """ Little hack to make sure that when you change something on these objects, it gets saved"""
        pass

    @api.multi
    def _compute_reserved_lot_ids(self):
        for record in self:
            record.reserved_lot_ids |= record.raw_move_line_ids.mapped('lot_id').filtered(lambda r: r.product_qty != 0)

    @api.depends('workorder_ids')
    def _compute_consumed_move(self):
        for production in self:
            production.move_consumed_ids = self.env['stock.move'].search(
                [('workorder_id', 'in', production.workorder_ids.ids)])

    def _generate_raw_move(self, bom_line, line_data):
        self.location_virtual_id = self.product_id.property_stock_production
        return super(MrpProduction, self)._generate_raw_move(bom_line, line_data)

    @api.depends('move_raw_ids.quantity_done', 'move_raw_ids.product_qty')
    def _compute_service_amount(self):
        for production in self:
            service_amount = 0.0
            for move in production.move_raw_ids:
                if move.product_id.type != 'product':
                    qty = move.quantity_done or move.product_qty
                    service_amount += move.price_unit * qty
            for line in production.bom_id.bom_line_ids:
                if line.product_id.type == 'service' and line.product_id.property_subcontracted_service:
                    service_amount += line.product_id.standard_price * production.qty_produced*line.product_qty
            production.service_amount = abs(service_amount)

    def _set_service_amount(self):
        for production in self:
            service_amount = production.service_amount
            service_product = self.env['product.product']
            qty = False
            for move in production.move_raw_ids:
                if move.product_id.type != 'product':
                    service_product |= move.product_id
                    qty = move.quantity_done or move.product_qty
            for line in production.bom_id.bom_line_ids:
                if line.product_id.type == 'service' and line.product_id.property_subcontracted_service:
                    service_product |= line.product_id
            if len(service_product) == 1 and qty:
                price = service_amount / qty
                service_product.write({'standard_price': abs(price)})

    @api.multi
    def _calculate_amount(self, consumed_moves=False, force_planed_cost=False):
        for production in self:
            amount = own_amount = 0.0
            planned_cost = False
            product_qty = sum(move.quantity_done for move in production.move_finished_ids)

            if sum(move.quantity_done for move in production.move_raw_ids) == 0 \
                    or production.state not in ['confirmed', 'done', 'cancel']:
                product_qty = production.product_qty
                if not force_planed_cost:
                    planned_cost = True
            # _logger.info("CALCULATEE PRODUCTION %s" % planned_cost)
            if planned_cost:
                for move in production.move_raw_ids:
                    if move.product_id.type in ('product', 'consu'):
                        coef = 1
                        qty = move.product_id.qty_at_date
                        if qty != 0:
                            price_unit = move.product_id.stock_value / qty
                        else:
                            price_unit = 0.0
                        if move.bom_line_id:
                            coef = 1 + move.bom_line_id.loss / 100
                        qty = move.product_qty * coef
                        if move.product_uom != move.product_id.uom_id:
                            qty = move.product_uom._compute_quantity(move.product_qty, move.product_id.uom_id) * coef
                        operations = production.routing_id.operation_ids.filtered(
                            lambda r: r.user_product_id == move.product_id or r.material_product_id == move.product_id)
                        operation_products = [x.user_product_id for x in operations]
                        operation_products += [x.material_product_id for x in operations]
                        time_cycle_manual = [x.time_cycle_manual for x in operations if x.time_cycle == 'manual']
                        if move.product_id in operation_products and time_cycle_manual:
                            amount += price_unit * qty * mean(time_cycle_manual)
                            if move.product_id.product_tmpl_id.own_mrp_component:
                                own_amount += price_unit * qty * mean(time_cycle_manual)
                        else:
                            # _logger.info(
                            #     "PRODUCT %s(%s)" % (move.product_id.display_name, price_unit))
                            if move.product_id.product_tmpl_id.own_mrp_component:
                                # _logger.info("OWN %s(%s)" % (move.product_id.display_name, price_unit))
                                own_amount += price_unit * qty
                            else:
                                amount += price_unit * qty
                product_qty = production.product_qty
            else:
                info = []
                if not consumed_moves:
                    consumed_moves = production.move_raw_ids.filtered(lambda x: x.state == 'done')
                for move in consumed_moves.sorted(lambda r: r.display_name):
                    if move.product_id.type in ('product', 'consu'):
                        # if self._context.get('force_accounting_date'):
                        #     product = move.product_id.with_context(
                        #         dict(self._context, to_date=self._context['force_accounting_date']))
                        #     if product.qty_at_date != 0:
                        #         move.price_unit = product.account_value / product.qty_at_date
                        #     qty_at_time = product.qty_at_date

                        qty_at_time = 0.0  # not used
                        price_unit = move.price_unit

                        if move.product_id.type == 'consu' and price_unit == 0.0:
                            price_unit = move.product_id.standard_price * move.product_uom.factor / move.product_id.uom_id.factor
                            move.price_unit = price_unit

                        if move.product_id.type == 'consu' \
                                and move.workorder_id.operation_id \
                                and (move.workorder_id.operation_id.user_product_id == move.product_id or
                                     move.workorder_id.operation_id.material_product_id == move.product_id):
                            if move.product_id == move.workorder_id.operation_id.user_product_id:
                                price_unit = move.workorder_id.user_price_unit
                            if move.product_id == move.workorder_id.operation_id.material_product_id:
                                price_unit = move.workorder_id.material_price_unit
                            # price_unit = price_unit == 0.0 and move.product_id.standard_price

                            if move.quantity_done == 0.0:
                                cycle_number = math.ceil(
                                    product_qty / move.workorder_id.operation_id.workcenter_id.capacity)
                                time_cycle = move.workorder_id.operation_id.get_time_cycle(quantity=product_qty,
                                                                                           product=production.product_id)
                                duration_expected = (
                                        cycle_number * time_cycle * 100.0 / move.workorder_id.operation_id.workcenter_id.time_efficiency)
                                move.move_line_ids.write({
                                    'qty_done': move.bom_line_id.product_qty * duration_expected * 60,
                                })
                            # price_unit = price_unit != 0.0 and move.product_id.standard_price

                        # _logger.info("PRICE PRICE %s:%s:%s" % (price_unit, move.price_unit, move.workorder_id.operation_id and move.workorder_id.operation_id.user_product_id or 'NO OPERATION'))

                        for move_line in move.move_line_ids.filtered(lambda r: r.state == 'done'):
                            qty = move_line.qty_done
                            valued_quantity = move_line.product_uom_id. \
                                _compute_quantity(qty, move_line.product_id.uom_id)
                            # qty = move.product_uom._compute_quantity(qty, move.product_id.uom_id)
                            amount_line = production.company_id.currency_id.round(abs(price_unit) * valued_quantity)
                            if move_line.product_id.product_tmpl_id.own_mrp_component:
                                own_amount += amount_line
                            else:
                                amount += amount_line
                            info.append([move.product_id.display_name,
                                         valued_quantity,
                                         abs(price_unit),
                                         amount_line,
                                         amount])
                            # _logger.info("AMOUNT %s(%s)-%s: \n(%s*%s, %s) = %s" % (
                            #     move.product_id.display_name, move.product_id.type, qty, valued_quantity,
                            #     abs(price_unit),
                            #     production.company_id.currency_id.round(abs(price_unit) * valued_quantity), amount,
                            # ))
                # force compute again service amount before use in calculation
                production._compute_service_amount()

                msg = "<table><thead><tr><th colspan='100' style='padding-left: 5px; padding-right: 5px;'>"
                msg += _("Info for calculations lines")
                msg += "</th></tr>"
                msg += "<tr><th>"
                msg += _('Component')
                msg += "</th>"
                msg += "<th>"
                msg += _('UOM Quantity')
                msg += "</th>"
                msg += "<th>"
                msg += _('Price unit')
                msg += "</th>"
                msg += "<th>"
                msg += _('Amount')
                msg += "</th>"
                msg += "<th>"
                msg += _('Subtotal')
                msg += "</th>"
                msg += "</tr></thead>"
                msg += "<tbody>"
                for line in info:
                    msg += "<tr>"
                    for col in line:
                        msg += "<td style='padding-left: 5px; padding-right: 5px;'>%s</td>" % col
                    msg += "</tr>"
                msg += "<tr><td colspan='100' style='padding-left: 5px; padding-right: 5px;'>"
                msg += _('Additional amount: %s') % production.service_amount
                msg += "</td></tr>"
                msg += "</tbody>"
                msg += "<tfoot><tr><td colspan='100' style='padding-left: 5px; padding-right: 5px;'>"
                msg += _('Summarize: %s for %s = %s') % (product_qty, amount, amount / product_qty)
                msg += "</td></tr></tfoot></table>"
                production.message_post(body=msg)
            amount += production.service_amount
            production.amount = amount
            production.own_amount = own_amount
            if product_qty > 0.0:
                production.calculate_price = amount / product_qty
                production.own_calculate_price = own_amount / product_qty

    def _cal_price(self, consumed_moves):
        for production in self:
            production._calculate_amount(consumed_moves, force_planed_cost=True)
            production.product_id.own_standard_price = production.own_calculate_price
            # qty_total_productions = sum(x.quantity_done for x in production.move_finished_ids)
            for product in production.move_finished_ids:
                product.price_unit = production.calculate_price
                product.value = production.amount
                product.own_value = production.own_amount
                product.own_price_unit = production.own_calculate_price
                product.product_price_update_before_done()
                # _logger.info("UNIT PRICE %s(%s:%s)" % (product.price_unit, production.calculate_price, production.own_calculate_price))
        return super(MrpProduction, self)._cal_price(consumed_moves)

    @api.multi
    def check_service_invoiced(self):
        for production in self:
            service_amount = 0
            for line in production.bom_id.bom_line_ids:
                if line.product_id.type == 'service' and line.product_id.property_subcontracted_service:
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
            production.write({'service_amount': abs(service_amount)})

    @api.multi
    def _account_entry_move(self):
        pass

    @api.multi
    def post_inventory(self):
        # check for service cost
        for record in self:
            record.check_service_invoiced()
            moves_to_do = record.move_raw_ids.filtered(
                lambda r: r.state not in (
                    'done', 'cancel') and r.product_id.type == 'consu' and r.quantity_done > 0 and r.price_unit != 0.0)
            for move in moves_to_do.filtered(lambda m: m.product_qty == 0.0 and m.quantity_done > 0):
                move.product_uom_qty = move.quantity_done
            for move in moves_to_do:
                move._account_entry_move()
            record._account_entry_move()
        # this is only to populate raw materials
        return super(MrpProduction, self).post_inventory()

    @api.multi
    def unpost_inventory(self, to_unpost_moves):
        for production in self:
            moves = self.env['account.move']
            for move_line in production.acc_move_line_ids:
                move = move_line.move_id
                if move.stock_move_id and move.stock_move_id.id not in to_unpost_moves.ids:
                    continue
                if move.state == 'posted':
                    moves |= move

            if moves:
                for move in moves:
                    if move.state == 'draft':
                        move.unlink()
                        continue
                    ret = move.button_cancel()
                    if ret:
                        move.unlink()

    @api.onchange('is_locked')
    @api.multi
    def onchange_is_locked(self):
        self.ensure_one()
        if self.state == 'done' and not self.is_locked:
            self.rebuild_account_move()

    @api.multi
    def rebuild_account_move(self):
        for production in self:
            # !!! remove raw_moves if work with product re-calculate !!!
            raw_moves = production.move_raw_ids.filtered(lambda x: x.state == 'done')
            if self._context.get('force_only_production'):
                raw_moves = self.env['stock.move']
            final_moves = production.move_finished_ids.filtered(lambda x: x.state == 'done')
            production.unpost_inventory(raw_moves + final_moves)
            production.with_context(dict(self._context, force_accounting_date=production.date_finished)). \
                _cal_price(production.move_raw_ids.filtered(lambda x: x.state == 'done'))
            for move in raw_moves:
                # _logger.info("MOVE COMPONENTS %s(%s)" % (move.price_unit, move.value))
                move.with_context(dict(self._context,
                                       rebuld_try=True,
                                       force_accounting_date=production.date_finished,
                                       force_valuation=True)).rebuild_account_move()
            for move in final_moves:
                # _logger.info("MOVE PRODUCTIONS %s=%s(%s)" % (production.calculate_price, move.price_unit, move.value))
                move.with_context(dict(self._context,
                                       rebuld_try=True,
                                       force_accounting_date=production.date_finished)).rebuild_account_move()
            production._account_entry_move()

    @api.multi
    def open_view_consumptions(self):
        # wiz = self.env['mrp.production.view.consumptions'].create({})
        view = self.env.ref('barcode_mrp_workorder.mrp_production_line_tree_view')
        action = self.env.ref('barcode_mrp_workorder.act_mrp_production_line_open').read()[0]
        action.update({
            'domain': [('id', 'in', self.production_line_ids.ids)]
        })
        return action

    @api.multi
    def unlink(self):
        for record in self:
            change_production_qty = self.env['change.production.qty'].search([('mo_id', '=', record.id)])
            if change_production_qty:
                change_production_qty.unlink()
        return super(MrpProduction, self).unlink()

    @api.multi
    def update_procurement_for_moves(self):
        for production in self:
            if production.sub_production == 'sub':
                update_qty_wizard = self.env['change.production.qty'].create({
                    'mo_id': production.id,
                    'product_qty': production.product_qty,
                })
                update_qty_wizard.change_prod_qty()

    @api.multi
    @job(default_channel='root.mrp')
    def server_update_procurement_for_moves(self):
        for production in self:
            if production.sub_production == 'sub':
                update_qty_wizard = self.env['change.production.qty'].create({
                    'mo_id': production.id,
                    'product_qty': production.product_qty,
                })
                update_qty_wizard.change_prod_qty()

    def _generate_raw_moves(self, exploded_lines):
        res = super(MrpProduction, self)._generate_raw_moves(exploded_lines)
        for record in self:
            record._calculate_amount(record.move_raw_ids.filtered(lambda x: x.state not in ('done', 'cancel')))
        return res

    @api.multi
    def _generate_moves(self):
        for production in self:
            production._generate_finished_moves()
            factor = production.product_uom_id._compute_quantity(production.product_qty,
                                                                 production.bom_id.product_uom_id) / production.bom_id.product_qty
            boms, lines = production.bom_id.explode(production.product_id, factor,
                                                    picking_type=production.bom_id.picking_type_id)
            production._generate_raw_moves(lines)
            # Check for all draft moves whether they are mto or not
            production._adjust_procure_method()
            production.move_raw_ids.with_context(
                dict(self._context, selection_follow=self.sub_production))._action_confirm()
            production._calculate_amount()
        return True

    @api.multi
    def _update_raw_move(self, bom_line, line_data):
        quantity = line_data['qty']
        self.ensure_one()
        move = self.move_raw_ids.filtered(
            lambda x: x.bom_line_id.id == bom_line.id and x.state not in ('done', 'cancel'))
        if move:
            # _logger.info("UPDATE %s:%s:%s:%s:%s:%s:%s" % (quantity, move[0].procure_method,
            # self.sub_production, move, bom_line.child_bom_id, move[0].raw_material_production_id, move[0].move_orig_ids))
            if move[0].procure_method == 'make_to_stock' and bom_line.child_bom_id:
                move[0].procure_method = 'make_to_order'
            if quantity > 0:
                production = move[0].raw_material_production_id
                production_qty = production.product_qty - production.qty_produced
                move[0].write({'product_uom_qty': quantity})
                if move[0].procure_method == 'make_to_order' \
                        and self.sub_production == 'sub' \
                        and bom_line.child_bom_id \
                        and not move[0].move_orig_ids:
                    _logger.info("PROCURE %s" % move[0].move_orig_ids)
                    move[0].with_context(dict(self._context,
                                              selection_follow=self.sub_production))._action_confirm()
                move[0]._recompute_state()
                move[0]._action_assign()
                move[0].unit_factor = production_qty and (quantity - move[0].quantity_done) / production_qty or 1.0
            elif quantity < 0:  # Do not remove 0 lines
                if move[0].quantity_done > 0:
                    raise UserError(
                        _('Lines need to be deleted, but can not as you still have some quantities to consume in them. '))
                move[0]._action_cancel()
                move[0].unlink()
            self._calculate_amount()
            return move
        else:
            self._generate_raw_move(bom_line, line_data)


mrpproduction._generate_moves = MrpProduction._generate_moves
mrpproduction._update_raw_move = MrpProduction._update_raw_move

