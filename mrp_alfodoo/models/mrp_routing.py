# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.addons.cmis_field import fields as cmis


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    worksheet_alfresco_folder = cmis.CmisFolder()
    worksheet_alfresco_document = fields.Char("Link to document")
