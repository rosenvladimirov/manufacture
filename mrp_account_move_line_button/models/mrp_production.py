# Copyright 2026 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    # Брой счетоводни редове (journal items), които производството отваря.
    # Базира се на account_move_line_ids от account_move_line_mrp_info, но брои
    # пълните записи (двете страни — дебит и кредит) на свързаните вальори.
    account_move_line_count = fields.Integer(
        string="Journal Items Count",
        compute="_compute_account_move_line_count",
    )

    @api.depends("account_move_line_ids")
    def _compute_account_move_line_count(self):
        for production in self:
            # .move_id.line_ids разгръща всеки свързан запис до пълните му редове,
            # за да съвпада броячът с това, което копчето показва.
            production.account_move_line_count = len(
                production.account_move_line_ids.move_id.line_ids
            )

    def action_view_account_move_lines(self):
        """Отваря дебитните и кредитните движения на счетоводните записи,
        породени от това производство, в стандартния изглед
        ``account.view_move_line_tree``."""
        self.ensure_one()
        # Тръгваме от свързаните редове, но показваме целите записи, за да се
        # виждат и двете страни (дебит и кредит) на всяка осчетоводена операция.
        move_lines = self.account_move_line_ids.move_id.line_ids
        return {
            "name": _("Journal Items"),
            "type": "ir.actions.act_window",
            "res_model": "account.move.line",
            "view_mode": "list,form",
            "views": [
                (self.env.ref("account.view_move_line_tree").id, "list"),
                (False, "form"),
            ],
            "domain": [("id", "in", move_lines.ids)],
            "context": {
                "create": False,
                "search_default_group_by_mrp_production": 1,
            },
            "target": "current",
        }
