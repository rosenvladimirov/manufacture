#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class StockMove(models.Model):
    _inherit = "stock.move"

    distribution_coefficient = fields.Float(
        "Distribution Coefficient",
        default=0.0,
    )
    distribution_coefficient_avg = fields.Float(
        "Weighted Coefficient",
        compute="_compute_distribution_coefficient_avg",
        store=True,
    )
    is_distribution_master = fields.Boolean(
        "Distribution Master",
        default=False,
    )
    base_distribution_qty = fields.Float(
        "Base Material Qty",
        default=0.0,
    )
    distribution_log_ids = fields.One2many(
        "mrp.production.coefficient.log",
        "move_id",
        string="Distribution Coefficient Logs",
    )
    distribution_log_count = fields.Integer(
        compute="_compute_distribution_log_count",
    )

    @api.depends("distribution_log_ids")
    def _compute_distribution_log_count(self):
        for move in self:
            move.distribution_log_count = len(move.distribution_log_ids)

    @api.depends("distribution_log_ids.coefficient", "distribution_log_ids.planned_qty")
    def _compute_distribution_coefficient_avg(self):
        for move in self:
            logs = move.distribution_log_ids
            total_qty = sum(log.planned_qty for log in logs)
            if total_qty:
                weighted = sum(log.coefficient * log.planned_qty for log in logs)
                move.distribution_coefficient_avg = weighted / total_qty
            else:
                move.distribution_coefficient_avg = 0.0

    def _get_distribution_master_move(self):
        self.ensure_one()
        production = self.raw_material_production_id
        if not production:
            return self.env["stock.move"]
        return production.move_raw_ids.filtered("is_distribution_master")[:1]

    def _adjust_master_distribution(self, delta):
        """Adjusts master distribution; prevents negative coefficient; updates quantity"""
        self.ensure_one()
        if not delta:
            return
        master_move = self._get_distribution_master_move()
        if not master_move:
            return
        new_value = master_move.distribution_coefficient - delta
        if float_compare(new_value, 0.0, precision_digits=6) < 0:
            raise ValidationError(
                _("Distribution coefficient exceeds available master share.")
            )
        master_qty = master_move.base_distribution_qty * new_value
        master_move.with_context(
            skip_distribution_adjust=True,
            skip_distribution_log=True,
        ).write(
            {
                "distribution_coefficient": new_value,
                "product_uom_qty": master_qty,
            }
        )

    def _log_distribution_coefficient(self):
        self.ensure_one()
        if self.env.context.get("skip_distribution_log"):
            return
        if self.is_distribution_master:
            return
        if not self.raw_material_production_id:
            return
        self.env["mrp.production.coefficient.log"].create(
            {
                "move_id": self.id,
                "coefficient": self.distribution_coefficient,
                "planned_qty": self.product_uom_qty,
                "base_distribution_qty": self.base_distribution_qty,
            }
        )

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        if self.env.context.get("skip_distribution_adjust"):
            return moves
        for vals, move in zip(vals_list, moves):
            if move.is_distribution_master:
                if move.base_distribution_qty:
                    move.with_context(
                        skip_distribution_adjust=True,
                        skip_distribution_log=True,
                    ).write(
                        {
                            "product_uom_qty": move.base_distribution_qty
                            * move.distribution_coefficient
                        }
                    )
                continue
            if move.base_distribution_qty:
                base_qty = move.base_distribution_qty
                if "product_uom_qty" in vals:
                    coeff = base_qty and (move.product_uom_qty / base_qty) or 0.0
                    if coeff != move.distribution_coefficient:
                        move.with_context(
                            skip_distribution_adjust=True,
                            skip_distribution_log=True,
                        ).write({"distribution_coefficient": coeff})
                else:
                    coeff = move.distribution_coefficient
                move._adjust_master_distribution(coeff)
                move.with_context(
                    skip_distribution_adjust=True,
                    skip_distribution_log=True,
                ).write({"product_uom_qty": base_qty * coeff})
                move._log_distribution_coefficient()
        return moves

    def write(self, vals):
        if self.env.context.get("skip_distribution_adjust"):
            return super().write(vals)
        if len(self) > 1 and (
            "product_uom_qty" in vals or "distribution_coefficient" in vals
        ):
            result = True
            for move in self:
                result = move.write(vals) and result
            return result
        move = self[:1]
        if not move:
            return super().write(vals)
        old_coeff = move.distribution_coefficient
        old_production = move.raw_material_production_id
        res = super().write(vals)
        if move.is_distribution_master:
            if move.base_distribution_qty:
                move.with_context(
                    skip_distribution_adjust=True,
                    skip_distribution_log=True,
                ).write(
                    {
                        "product_uom_qty": move.base_distribution_qty
                        * move.distribution_coefficient
                    }
                )
            return res
        if "product_uom_qty" in vals and "distribution_coefficient" not in vals:
            base_qty = move.base_distribution_qty
            coeff = base_qty and (move.product_uom_qty / base_qty) or 0.0
            move.with_context(
                skip_distribution_adjust=True,
                skip_distribution_log=True,
            ).write({"distribution_coefficient": coeff})
        new_coeff = move.distribution_coefficient
        if old_production and old_production != move.raw_material_production_id:
            old_master = old_production.move_raw_ids.filtered("is_distribution_master")[:1]
            if old_master:
                old_master.with_context(
                    skip_distribution_adjust=True,
                    skip_distribution_log=True,
                ).write(
                    {
                        "distribution_coefficient": old_master.distribution_coefficient
                        + old_coeff,
                        "product_uom_qty": old_master.base_distribution_qty
                        * old_master.distribution_coefficient,
                    }
                )
        delta = new_coeff - old_coeff
        if delta:
            move._adjust_master_distribution(delta)
        if move.base_distribution_qty:
            move.with_context(
                skip_distribution_adjust=True,
                skip_distribution_log=True,
            ).write(
                {"product_uom_qty": move.base_distribution_qty * new_coeff}
            )
        if "distribution_coefficient" in vals or "product_uom_qty" in vals:
            move._log_distribution_coefficient()
        return res

    def unlink(self):
        if self.env.context.get("skip_distribution_adjust"):
            return super().unlink()
        for move in self:
            if move.is_distribution_master:
                continue
            if move.raw_material_production_id and move.distribution_coefficient:
                move._adjust_master_distribution(-move.distribution_coefficient)
        return super().unlink()

    def action_open_distribution_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Distribution Coefficient History"),
            "res_model": "mrp.production.coefficient.log",
            "view_mode": "list,form",
            "target": "current",
            "domain": [("move_id", "=", self.id)],
        }
