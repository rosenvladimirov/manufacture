# coding: utf-8
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools, _

import logging

_logger = logging.getLogger(__name__)


class MrpTechnicalDocuments(models.Model):
    _name = "mrp.technical.documents"
    _description = "Collection of all technical and production documentations."
    _inherits = {'ir.attachment': 'ir_attachment_id', }

    ir_attachment_id = fields.Many2one('ir.attachment', string='Related attachment', required=True, ondelete='cascade')
    document_type_id = fields.Many2one('technical.documents.type', 'Type of technical document')
    routing_id = fields.Many2one('mrp.routing.workcenter', 'Routing')
    color = fields.Integer(string="Color")

    @api.onchange('routing_id')
    def _onchange_partner_id(self):
        for record in self:
            if record.routing_id and not record.res_model and not record.res_id:
                record.res_model, record.res_id = ('mrp.routing.workcenter', record.routing_id.id)


class TechnicalDocumentsType(models.Model):
    _name = "technical.documents.type"
    _description = "Global nomenclature for technical documents."

    active = fields.Boolean('Active', default=True,
                            help="If the active field is set to False, "
                                 "it will allow you to hide the Type documents without removing it.")
    name = fields.Char('Name', translate=True)
    code = fields.Char('Code')
