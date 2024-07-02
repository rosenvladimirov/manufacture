# coding: utf-8
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools, _

import logging

_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    technical_doc_ids = fields.Many2many('mrp.technical.documents', compute='_compute_technical_doc_ids',
                                         string='Technical documentation')

    @api.multi
    def _compute_technical_doc_ids(self):
        for record in self:
            technical_doc_ids = self.env['mrp.technical.documents'].search([('routing_id', '=', record.operation_id.id)])
            if technical_doc_ids:
                record.technical_doc_ids = technical_doc_ids
