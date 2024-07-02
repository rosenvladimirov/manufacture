# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round
from odoo.addons import decimal_precision as dp


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    show_final_lots = fields.Boolean('Show Final Lots', compute='_compute_show_lots')
    move_finished_ids = fields.One2many(
        'stock.move', compute='_compute_move_finished_ids', string='Finished Products')
    finished_move_line_ids = fields.One2many(
        'stock.move.line', compute='_compute_lines', inverse='_inverse_lines', string="Finished Product"
    )
    production_move_raw_ids = fields.One2many(
        'stock.move', string="Production move raw", compute="_compute_production_move_raw_ids"
    )
    

    @api.depends('production_id.product_id.tracking')
    def _compute_show_lots(self):
        for wo in self:
            production = self.production_id
            wo.show_final_lots = production.product_id.tracking != 'none'

    @api.depends('production_id')
    def _compute_move_finished_ids(self):
        for workorder in self:
            production = workorder.production_id
            workorder.move_finished_ids = production.move_finished_ids

    @api.depends('production_id.move_raw_ids')
    def _compute_production_move_raw_ids(self):
        for wo in self:
            wo.production_move_raw_ids = wo.production_id.move_raw_ids.filtered(
                lambda r: r.operation_id == wo.operation_id)

    def _inverse_lines(self):
        """ Little hack to make sure that when you change something on these objects, it gets saved"""
        pass

    @api.depends('production_id')
    def _compute_lines(self):
        for workorder in self:
            production = workorder.production_id
            workorder.finished_move_line_ids = production.move_finished_ids.mapped('move_line_ids')

    # moved in barcode_mrp_workorder
    # def action_open_wizard_view_stock_picking_add_product(self):
    #     action = self.env.ref('mrp_bom_losses.act_open_wizard_view_stock_picking_add_product').read()[0]
    #     action['context'] = {'default_workorder_id': self.id}
    #     return action

    def _generate_lot_ids(self):
        super(MrpWorkorder, self)._generate_lot_ids()
        for line in self.active_move_line_ids:
            production_id = self.production_id
            used_special_qty_ids = production_id.move_raw_ids. \
                filtered(lambda r: r.product_id == line.product_id)
            special_qty = used_special_qty = 0.0
            for used_line in used_special_qty_ids.mapped('move_line_ids').\
                    filtered(lambda r: r.lot_id == line.lot_id and r.lot_produced_id):
                special_qty += used_line.product_qty
                used_special_qty += used_line.qty_done
            if special_qty != 0.0:
                line.special_qty = abs(special_qty)
                line.used_special_qty = abs(used_special_qty)
                line.progress = line.used_special_qty / line.special_qty * 100

    @api.multi
    def record_production(self):
        res = super(MrpWorkorder, self).record_production()
        for workorder in self:
            production_id = workorder.production_id
            produce = 0.0
            producing = 0.0
            for x in production_id.move_finished_ids:
                produce = x.product_uom_qty
                producing = x.quantity_done
            produce = produce == 0.0 and 1.0 or produce
            production_id.progress = producing/produce*100

            if (self._context.get('record_silent') is None or not self._context.get('record_silent'))\
                    and len(workorder.product_id.packaging_ids.ids) > 0:
                packaging_quantity = workorder.product_id.packaging_ids[0].qty
                if producing / packaging_quantity == producing // packaging_quantity:
                    workorder.production_messages = "<br/> Maybe package (%s) is full" % packaging_quantity
        return res

    @api.model
    def create(self, values):
        if values.get("name"):
            values['name'] = "%s(%s)" % (values['name'], self.env['ir.sequence'].next_by_code('mrp.workorder'))
        if not values.get('name', False) or values['name'] == _('New'):
            values['name'] = self.env['ir.sequence'].next_by_code('mrp.workorder') or _('New')
        return super(MrpWorkorder, self).create(values)
