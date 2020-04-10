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

    def _inverse_lines(self):
        """ Little hack to make sure that when you change something on these objects, it gets saved"""
        pass

    @api.depends('production_id')
    def _compute_lines(self):
        for workorder in self:
            production = workorder.production_id
            workorder.finished_move_line_ids = production.move_finished_ids.mapped('move_line_ids')

    def action_open_wizard_view_stock_picking_add_product(self):
        action = self.env.ref('mrp_bom_losses.act_open_wizard_view_stock_picking_add_product').read()[0]
        action['context'] = {'default_workorder_id': self.id}
        return action
