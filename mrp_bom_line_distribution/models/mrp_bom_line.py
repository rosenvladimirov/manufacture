#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    distribution_coefficient = fields.Float(
        "Distribution Coefficient",
        default=0.0,
    )
    is_distribution_master = fields.Boolean(
        "Distribution Master",
        default=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if self.env.context.get("skip_distribution_adjust"):
            return lines
        for vals, line in zip(vals_list, lines):
            if line.is_distribution_master:
                continue
            if line.bom_id:
                base_qty = line.bom_id.base_distribution_qty
                if "product_qty" in vals:
                    coeff = base_qty and (line.product_qty / base_qty) or 0.0
                    if coeff != line.distribution_coefficient:
                        line.with_context(skip_distribution_adjust=True).write(
                            {"distribution_coefficient": coeff}
                        )
                else:
                    coeff = line.distribution_coefficient
                line._adjust_master_for_delta(coeff)
                line.with_context(skip_distribution_adjust=True).write(
                    {"product_qty": base_qty * coeff}
                )
            else:
                line._adjust_master_for_delta(line.distribution_coefficient)
        return lines

    def write(self, vals):
        if self.env.context.get("skip_distribution_adjust"):
            return super().write(vals)
        if "product_qty" in vals and len(self) > 1:
            for line in self:
                line.write(vals)
            return True
        if "product_qty" in vals:
            line = self[:1]
            if line and line.bom_id and not line.is_distribution_master:
                base_qty = line.bom_id.base_distribution_qty
                coeff = base_qty and (vals["product_qty"] / base_qty) or 0.0
                vals = dict(vals)
                vals["distribution_coefficient"] = coeff
        tracked = []
        for line in self:
            if line.is_distribution_master:
                continue
            tracked.append((line, line.bom_id, line.distribution_coefficient))
        res = super().write(vals)
        # Adjusts master distribution when BOM or coefficient changes
        for line, old_bom, old_coeff in tracked:
            if line.is_distribution_master:
                continue
            new_bom = line.bom_id
            new_coeff = line.distribution_coefficient
            if old_bom != new_bom:
                if old_bom:
                    old_bom._adjust_master_distribution(-old_coeff)
                if new_bom:
                    new_bom._adjust_master_distribution(new_coeff)
                if new_bom:
                    base_qty = new_bom.base_distribution_qty
                    line.with_context(skip_distribution_adjust=True).write(
                        {"product_qty": base_qty * new_coeff}
                    )
                continue
            delta = new_coeff - old_coeff
            if delta:
                line._adjust_master_for_delta(delta)
            if "distribution_coefficient" in vals and line.bom_id:
                base_qty = line.bom_id.base_distribution_qty
                line.with_context(skip_distribution_adjust=True).write(
                    {"product_qty": base_qty * new_coeff}
                )
        return res

    def unlink(self):
        if self.env.context.get("skip_distribution_adjust"):
            return super().unlink()
        for line in self:
            if line.is_distribution_master:
                continue
            if line.bom_id and line.distribution_coefficient:
                line.bom_id._adjust_master_distribution(-line.distribution_coefficient)
        return super().unlink()

    def _adjust_master_for_delta(self, delta):
        self.ensure_one()
        if not delta:
            return
        if not self.bom_id:
            return
        self.bom_id._adjust_master_distribution(delta)
