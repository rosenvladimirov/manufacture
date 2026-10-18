# Copyright 2025-2026 Rosen Vladimirov
#
# This file is available under a DUAL LICENSE:
#   1. GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
#      https://www.gnu.org/licenses/agpl-3.0.html
#   2. A commercial license from Rosen Vladimirov, for use without the obligations
#      of the AGPL. See LICENSE-COMMERCIAL.md. Contact: vladimirov.rosen@gmail.com
#
# Unless you hold a valid commercial license, your use of this file is governed
# by the AGPL-3.0-or-later.


from odoo import fields, models


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    # За ръчни (PRK / не-LogiKal) BoM-ове: MO-то консумира този компонент
    # само от посочения лот. Празно = нормално поведение. LogiKal forced
    # lots имат приоритет (виж mrp.production._get_move_raw_values).
    default_forced_lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Default Forced Lot",
        domain="[('product_id', '=', product_id)]",
        help="Lot to force on this component's raw move at MO confirm "
        "(reservation only, no split). The MO then consumes this component "
        "only from the given lot. Leave empty for the standard behaviour. "
        "Forced lots coming from other sources (e.g. LogiKal) take priority.",
    )
