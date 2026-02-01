#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    main_component_id = fields.Many2one(
        "product.product",
        string="Main Component",
    )
    base_distribution_qty = fields.Float(
        "Base Material Qty",
        default=1.0,
    )

    def _ensure_distribution_master_line(self):
        self.ensure_one()
        if not self.main_component_id:
            return self.env["mrp.bom.line"]
        master_line = self.bom_line_ids.filtered("is_distribution_master")[:1]
        if master_line:
            vals = {}
            if master_line.product_id != self.main_component_id:
                vals["product_id"] = self.main_component_id.id
            if master_line.sequence != 0:
                vals["sequence"] = 0
            if vals:
                master_line.with_context(skip_distribution_adjust=True).write(vals)
            return master_line
        return self.env["mrp.bom.line"].with_context(skip_distribution_adjust=True).create(
            {
                "bom_id": self.id,
                "product_id": self.main_component_id.id,
                "product_qty": self.base_distribution_qty,
                "distribution_coefficient": 1.0,
                "is_distribution_master": True,
                "sequence": 0,
            }
        )

    def _adjust_master_distribution(self, delta):
        """Adjusts master distribution coefficient by delta"""
        self.ensure_one()
        if not delta:
            return
        master_line = self._ensure_distribution_master_line()
        if not master_line:
            return
        new_value = master_line.distribution_coefficient - delta
        if float_compare(new_value, 0.0, precision_digits=6) < 0:
            raise ValidationError(
                _("Distribution coefficient exceeds available master share.")
            )
        master_qty = self.base_distribution_qty * new_value
        master_line.with_context(skip_distribution_adjust=True).write(
            {
                "distribution_coefficient": new_value,
                "product_qty": master_qty,
            }
        )

    def _recompute_master_distribution(self):
        """Recomputes master line distribution coefficient and quantity"""
        self.ensure_one()
        master_line = self._ensure_distribution_master_line()
        if not master_line:
            return
        other_lines = self.bom_line_ids.filtered(lambda line: not line.is_distribution_master)
        total = sum(other_lines.mapped("distribution_coefficient"))
        new_value = 1.0 - total
        if float_compare(new_value, 0.0, precision_digits=6) < 0:
            raise ValidationError(
                _("Distribution coefficient exceeds available master share.")
            )
        master_line.with_context(skip_distribution_adjust=True).write(
            {
                "distribution_coefficient": new_value,
                "product_qty": self.base_distribution_qty * new_value,
            }
        )

    def _recompute_distribution_quantities(self):
        """Recomputes distribution quantities based on master quantity"""
        self.ensure_one()
        if not self.bom_line_ids:
            return
        base_qty = self.base_distribution_qty
        for line in self.bom_line_ids:
            target_qty = base_qty * line.distribution_coefficient
            if line.product_qty != target_qty:
                line.with_context(skip_distribution_adjust=True).write(
                    {"product_qty": target_qty}
                )

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)
        for bom in boms:
            if bom.main_component_id:
                bom._recompute_master_distribution()
        return boms

    def write(self, vals):
        res = super().write(vals)
        if "main_component_id" in vals or "base_distribution_qty" in vals:
            for bom in self:
                if bom.main_component_id:
                    bom._recompute_master_distribution()
                if "base_distribution_qty" in vals:
                    bom._recompute_distribution_quantities()
        return res
