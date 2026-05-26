# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    # Replace the core UNIQUE(product, location, company, warehouse)
    # constraint with a no-op CHECK so Odoo does not recreate it on
    # registry load. The real uniqueness rule (parents-only on the
    # quadruple + (parent_id, lot_id) for children) is enforced via the
    # partial UNIQUE INDEXES created in `pre-migrate.py`.
    _sql_constraints = [
        (
            "product_location_check",
            "CHECK (TRUE)",
            "Replaced by partial unique indexes — see pre-migrate.py.",
        ),
    ]

    parent_id = fields.Many2one(
        comodel_name="stock.warehouse.orderpoint",
        string="Parent Orderpoint",
        ondelete="cascade",
        index=True,
        help="Lot-level orderpoints attach as children to a product-level "
        "parent. Children inherit product/location/warehouse from parent "
        "and add their own lot_id + min/max thresholds.",
    )

    child_ids = fields.One2many(
        comodel_name="stock.warehouse.orderpoint",
        inverse_name="parent_id",
        string="Lot Sub-rules",
        help="Per-lot reorder rules nested under this product-level "
        "orderpoint. Each child handles one specific lot; the standard "
        "scheduler picks them up automatically.",
    )

    lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Lot",
        ondelete="cascade",
        index=True,
        help="Lot this orderpoint targets. Set only on child orderpoints "
        "— leave empty for product-level (parent) rules. When the lot is "
        "deleted, the child orderpoint is removed automatically (cascade).",
    )

    is_lot_child = fields.Boolean(
        compute="_compute_is_lot_child",
        store=True,
        index=True,
        help="True when this orderpoint is a child rule (has parent_id "
        "and lot_id). Used by default search domains to hide children "
        "from the standard list view.",
    )

    child_count = fields.Integer(
        compute="_compute_child_count",
        string="Lot Sub-rules",
        help="Number of lot-level sub-rules under this orderpoint. "
        "Shown as a badge in the Replenishment Report to flag parents "
        "that drive per-lot procurement.",
    )

    @api.depends("child_ids")
    def _compute_child_count(self):
        for op in self:
            op.child_count = len(op.child_ids)

    allowed_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        compute="_compute_allowed_lot_ids",
        string="Allowed Lots",
        help="Lots eligible to be picked as `lot_id` for a sub-rule under "
        "this orderpoint. Computed from `_get_lot_domain()` — extend that "
        "method in dependent modules to add filters (supplier, attribute, "
        "production date, etc.).",
    )

    @api.depends("parent_id")
    def _compute_is_lot_child(self):
        """Any orderpoint with a parent is a child rule.

        Trigger on `parent_id` alone (not `lot_id`) so that incomplete
        children — newly added rows still missing their lot_id — are
        already filtered out of the Replenishment Report. The model
        constraint enforces `lot_id` at save time.
        """
        for op in self:
            op.is_lot_child = bool(op.parent_id)

    @api.depends("product_id")
    def _compute_allowed_lot_ids(self):
        """Re-evaluate the placeholder domain whenever product changes.

        Add `@api.depends(...)` for any field your override of
        `_get_lot_domain` reads, so the M2O picker stays reactive in
        the form view.
        """
        Lot = self.env["stock.lot"]
        for op in self:
            domain = op._get_lot_domain()
            op.allowed_lot_ids = Lot.search(domain) if domain is not None else Lot

    def _get_lot_domain(self):
        """Placeholder domain for the lot picker on sub-rules.

        Override in dependent modules to inject additional filters.
        Examples of common extensions:

            def _get_lot_domain(self):
                domain = super()._get_lot_domain()
                if self.preferred_supplier_id:
                    domain.append(("supplier_id", "=",
                                   self.preferred_supplier_id.id))
                return domain

        Remember to add the new dependency to `_compute_allowed_lot_ids`
        via `@api.depends(...)` so the picker reacts to changes.

        Return `None` to fall through to an empty recordset (rather than
        the default product-only domain).
        """
        self.ensure_one()
        if not self.product_id:
            return [("id", "=", 0)]
        return [("product_id", "=", self.product_id.id)]

    # ---------------------------------------------------------------- constraints

    @api.constrains("parent_id")
    def _check_max_depth(self):
        for op in self:
            if op.parent_id and op.parent_id.parent_id:
                raise ValidationError(
                    "Lot sub-rules cannot have their own sub-rules — "
                    "parent-child depth is limited to 2 levels."
                )
            if op.parent_id == op:
                raise ValidationError(
                    "Orderpoint cannot be its own parent."
                )

    @api.constrains("parent_id", "product_id", "lot_id")
    def _check_child_consistency(self):
        for op in self:
            if not op.parent_id:
                continue
            if op.product_id != op.parent_id.product_id:
                raise ValidationError(
                    f"Child orderpoint product ({op.product_id.display_name}) "
                    f"must match parent product ({op.parent_id.product_id.display_name})."
                )
            if not op.lot_id:
                raise ValidationError(
                    "A child orderpoint must have a Lot set."
                )
            if op.lot_id.product_id != op.parent_id.product_id:
                raise ValidationError(
                    f"Lot {op.lot_id.name} belongs to "
                    f"{op.lot_id.product_id.display_name}, not "
                    f"{op.parent_id.product_id.display_name}."
                )

    @api.constrains("lot_id", "parent_id")
    def _check_unique_lot_per_parent(self):
        for op in self:
            if not op.parent_id or not op.lot_id:
                continue
            dup = self.search([
                ("parent_id", "=", op.parent_id.id),
                ("lot_id", "=", op.lot_id.id),
                ("id", "!=", op.id),
            ], limit=1)
            if dup:
                raise ValidationError(
                    f"Lot {op.lot_id.name} already has a sub-rule under "
                    f"parent {op.parent_id.name}."
                )

    # ---------------------------------------------------------------- inheritance from parent

    @api.onchange("parent_id")
    def _onchange_parent_inherit(self):
        """Children inherit product/location/warehouse/route from parent."""
        for op in self:
            if not op.parent_id:
                continue
            op.product_id = op.parent_id.product_id
            op.location_id = op.parent_id.location_id
            op.warehouse_id = op.parent_id.warehouse_id
            op.company_id = op.parent_id.company_id
            if not op.route_id:
                op.route_id = op.parent_id.route_id

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-fill child fields inherited from parent at create time."""
        for vals in vals_list:
            parent_id = vals.get("parent_id")
            if not parent_id:
                continue
            parent = self.browse(parent_id)
            vals.setdefault("product_id", parent.product_id.id)
            vals.setdefault("location_id", parent.location_id.id)
            vals.setdefault("warehouse_id", parent.warehouse_id.id)
            vals.setdefault("company_id", parent.company_id.id)
            if parent.route_id:
                vals.setdefault("route_id", parent.route_id.id)
        return super().create(vals_list)

    # ---------------------------------------------------------------- procurement

    def _prepare_procurement_values(self, date=False, group=False):
        """Attach forced_lot_ids when this is a child (lot-level) orderpoint.

        Behavior:
        - Child orderpoint with `lot_id` → procurement carries
          `forced_lot_ids = [lot_id]` so the resulting MO/PO is locked
          to that single lot.
        - Parent (product-level) orderpoint → fall back to pending-move
          forced lots collection (existing LogiKal flow). Acts as the
          "orphan lot" rule for procurements not matching any child.
        """
        values = super()._prepare_procurement_values(date=date, group=group)
        if self.lot_id:
            values["forced_lot_ids"] = self.lot_id
            return values
        pending = self._get_forced_lots()
        if pending:
            values["forced_lot_ids"] = pending
        return values

    def _get_qty_to_order(self, force_visibility_days=False,
                         qty_in_progress_by_orderpoint=None):
        """Children-bearing parents do not order at product level.

        When a parent has at least one child sub-rule, the children carry
        the replenishment policy — parent's qty_to_order is suppressed so
        the cron does not double-order. Lots not registered as children
        still flow through the parent's product_min/max as the orphan
        fallback (via standard Odoo handling on demand).

        Lot-level children and product-level parents without children
        fall through to the standard compute.
        """
        if not self.lot_id and self.child_ids:
            return 0.0
        return super()._get_qty_to_order(
            force_visibility_days=force_visibility_days,
            qty_in_progress_by_orderpoint=qty_in_progress_by_orderpoint,
        )

    def _get_product_context(self, visibility_days=0):
        """Scope stock reads to this lot for child orderpoints.

        Child orderpoints compute their qty_forecast/qty_on_hand from
        quants of `lot_id` only, not all lots of the product. Standard
        Odoo passes `location` in the context; we also inject
        `lot_id` so `product.virtual_available` filters correctly.
        """
        ctx = super()._get_product_context(visibility_days=visibility_days)
        if self.lot_id:
            ctx["lot_id"] = self.lot_id.id
        return ctx

    # ---------------------------------------------------------------- existing pending-move lots

    def _get_forced_lots(self):
        self.ensure_one()
        moves = self.env["stock.move"].search([
            ("product_id", "=", self.product_id.id),
            ("location_id", "=", self.location_id.id),
            ("state", "in", ("waiting", "confirmed", "partially_available")),
            ("forced_lot_ids", "!=", False),
        ])
        if not moves:
            return self.env["stock.lot"]
        lots = moves.mapped("forced_lot_ids")
        _logger.info(
            "Orderpoint %s (%s): found %d forced lot(s) from %d pending move(s)",
            self.name, self.product_id.display_name, len(lots), len(moves),
        )
        return lots
