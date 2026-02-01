#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class MRPBomLine(models.Model):
    _inherit = "mrp.bom.line"

    loss = fields.Float('Losses')
