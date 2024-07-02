# © 2015 Oihane Crucelaegui - AvanzOSC
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import models, fields


class MrpBom(models.Model):
    _inherit = 'mrp.bom.line'

    notes = fields.Text(related='product_id.description_manufacture', store=True)
    ref_note = fields.Char('REF', related='product_id.ref_note_manufacture', store=True)
