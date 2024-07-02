# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.addons import decimal_precision as dp
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare

import logging
_logger = logging.getLogger(__name__)


class MrpSplitProductionWizardLine(models.TransientModel):
    _name = "wiz.mrp.split.production.line"

    production_split_wizard_id = fields.Many2one(
        string="MRP production Wizard",
        comodel_name="wiz.mrp.split.production",
        ondelete="cascade",
        required=True,
    )
    sequence = fields.Integer(
        string="Sequence",
    )
    production_id = fields.Many2one(
        comodel_name='mrp.production',
        string='Production',
    )
    bom_id = fields.Many2one(
        comodel_name='mrp.bom',
        string='Bom',
    )
    bom_ids = fields.Many2many(
        comodel_name='mrp.bom',
        string='Boms',
        compute='_compute_bom_ids',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        related='production_id.product_id',
        string='Product to produce'
    )
    oring_product_qty = fields.Float(
        string='Oring Quantity To Produce',
        digits=dp.get_precision('Product Unit of Measure'),
        readonly=True,
    )
    product_qty = fields.Float(
        string='Quantity To Produce',
        digits=dp.get_precision('Product Unit of Measure'),
        readonly=True,
    )
    picking_type_id = fields.Many2one(
        'stock.picking.type', 'Operation Type',
        default=lambda self: self.env['wiz.mrp.split.production']._get_default_picking_type(),
        required=True)
    location_src_id = fields.Many2one(
        comodel_name='stock.location',
        string='Source material location',
    )
    location_dest_id = fields.Many2one(
        comodel_name='stock.location',
        string='Destination production location',
    )
    date_planned_start = fields.Datetime(
        'Deadline Start', default=fields.Datetime.now,
        )
    date_planned_finished = fields.Datetime(
        'Deadline End', default=fields.Datetime.now,
    )
    split_to = fields.Integer(
        string='Split to parts'
    )
    part = fields.Float(
        string='Part size',
        digits=dp.get_precision('Product Unit of Measure'),
    )
    rest = fields.Float(
        string='Res of parts',
        digits=dp.get_precision('Product Unit of Measure'),
    )

    @api.multi
    def _compute_bom_ids(self):
        for record in self:
            record.bom_ids = [(6, False, record.product_id.bom_ids.ids)]

    @api.onchange('split_to')
    @api.depends('part', 'rest')
    def onchange_split_to(self):
        for record in self:
            record.part, record.rest = divmod(record.product_qty, record.split_to)
