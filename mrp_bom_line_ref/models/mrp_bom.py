# © 2015 Oihane Crucelaegui - AvanzOSC
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import models, fields


class MrpBom(models.Model):
    _inherit = 'mrp.bom.line'

    ref = fields.Text()
    ref_ref = fields.Char()
    ref_note = fields.Char('REF')
