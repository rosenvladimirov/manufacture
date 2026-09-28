# Copyright 2026 Rosen Vladimirov
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models
from odoo.osv import expression


class StockMove(models.Model):
    _inherit = "stock.move"

    def _trigger_assign(self):
        """Автоматична резервация след done — и там, където редът е КАЦНАЛ.

        Ядрото (stock/models/stock_move.py, _trigger_assign) търси чакащите
        движения с `location_id = move.location_dest_id` — точно равенство с
        местоназначението на ДВИЖЕНИЕТО. Putaway обаче слага реда на лист под
        него (WH/Stock → WH/Stock/Рафт, миграцията от 11.09) и чакащите
        движения, които теглят от листа, не се виждат: остават confirmed до
        ръчно action_assign или шедулера (задача 90, STOR/00254 → MO/01899–01905).

        Тук домейнът за всяко движение е местоназначението му ПЛЮС
        местоназначенията на редовете му. НЕ child_of: той би резервирал и
        движения от буфери под склада (Pre-Production, Remnant/Offcut), до
        които заприхождаването изобщо не е стигнало.

        Методът е копие на ядрото с тази една разлика — редът на резервиране
        (приоритет, дата, собствената група първо) е запазен, затова не се
        вика super() с втори проход.
        """
        if not self or self.env["ir.config_parameter"].sudo().get_param(
            "stock.picking_no_auto_reserve"
        ):
            return

        domains = [
            [
                ("product_id", "=", move.product_id.id),
                (
                    "location_id",
                    "in",
                    (
                        move.location_dest_id
                        | move.move_line_ids.location_dest_id
                    ).ids,
                ),
            ]
            for move in self
        ]
        static_domain = [
            ("state", "in", ["confirmed", "partially_available"]),
            ("procure_method", "=", "make_to_stock"),
            "|",
            ("reservation_date", "<=", fields.Date.today()),
            ("picking_type_id.reservation_method", "=", "at_confirm"),
        ]
        moves_to_reserve = self.env["stock.move"].search(
            expression.AND([static_domain, expression.OR(domains)]),
            order="priority desc, date asc, id asc",
        )
        moves_to_reserve = moves_to_reserve.sorted(
            key=lambda m: m.group_id.id in self.group_id.ids, reverse=True
        )
        moves_to_reserve._action_assign()
