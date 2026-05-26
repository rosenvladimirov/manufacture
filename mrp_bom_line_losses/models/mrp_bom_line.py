#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MRPBomLine(models.Model):
    _inherit = "mrp.bom.line"

    loss = fields.Float(
        string="Loss / Efficiency",
        help="Positive = extra consumption (scrap/loss). Negative = efficiency gain (consume less). "
             "Value is a ratio, e.g. 0.10 = +10%% loss, -0.05 = -5%% efficiency gain.",
    )

    @api.constrains("loss")
    def _check_loss_factor(self):
        """Allow both positive and negative losses but forbid factor <= 0."""
        for line in self:
            if line.loss <= -1.0:
                raise ValidationError(
                    _("Loss must be greater than -100%% (factor would be <= 0).")
                )
