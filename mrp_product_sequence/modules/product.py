# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class Product(models.Model):
    _inherit = "product.product"

    lot_sequence_id = fields.Many2one(
        "ir.sequence",
        string="Entry Sequence",
        help="This field contains the information related to the "
        "numbering of lots.",
        copy=False,
    )
    lot_sequence_number_next = fields.Integer(
        string="Next Number",
        help="The next sequence number will be used for the next lot.",
        compute="_compute_lot_seq_number_next",
        inverse="_inverse_lot_seq_number_next",
    )

    @api.multi
    # do not depend on 'lot_sequence_id.date_range_ids', because
    # lot_sequence_id._get_current_sequence() may invalidate it!
    @api.depends(
        "lot_sequence_id.use_date_range", "lot_sequence_id.number_next_actual"
    )
    def _compute_lot_seq_number_next(self):
        """ Compute 'lot_sequence_number_next' according to the current
            sequence in use, an ir.sequence or an ir.sequence.date_range.
        """
        for product in self:
            if product.lot_sequence_id:
                sequence = product.lot_sequence_id._get_current_sequence()
                product.lot_sequence_number_next = sequence.number_next_actual
            else:
                product.lot_sequence_number_next = 1

    @api.multi
    def _inverse_lot_seq_number_next(self):
        """
        Inverse 'lot_sequence_number_next' to edit the current sequence next
        number
        """
        for product in self:
            if product.lot_sequence_id and product.lot_sequence_number_next:
                sequence = product.lot_sequence_id._get_current_sequence()
                sequence.sudo().number_next = product.lot_sequence_number_next
