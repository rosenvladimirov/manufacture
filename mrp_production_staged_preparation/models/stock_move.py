# Copyright 2026 BL Consulting
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class StockMove(models.Model):
    """Block MTO chain on raw moves while parent MO is staged 'intermediate'.

    Why this override exists:

    Native ``mrp.production.action_confirm`` calls
    ``move_raws_to_adjust._adjust_procure_method()`` before
    ``_action_confirm(merge=False)``. ``_adjust_procure_method`` searches
    ``stock.rule`` records by ``location_src_id=move.location_id`` and
    ``location_dest_id=move.location_dest_id`` and copies the matched
    rule's ``procure_method`` onto the move.

    In 2/3-step warehouses Odoo creates a global MTO rule
    ``manufacture_mto_pull_id`` with exact source ``lot_stock_id`` and
    destination ``production_location`` (see
    ``mrp/models/stock_warehouse.py``). The rule is active for ALL warehouses
    with active manufacture route, not just ``mrp_one_step``.

    Our preparation-state override sets raw ``location_id = lot_stock_id``
    (to mimic 1-step behaviour). ``_adjust_procure_method`` then matches the
    MTO rule and flips ``procure_method`` to ``make_to_order``. The
    subsequent ``_action_confirm`` triggers the procurement chain which
    decomposes Stock→Production via ``pbm_route_id`` rules
    (Stock→pbm_loc → pbm_loc→Production), giving birth to a Pick picking
    we explicitly want to suppress.

    Fix: short-circuit ``_adjust_procure_method`` for raw moves belonging to
    a MO in ``state='preparation'`` — force ``make_to_stock`` regardless of
    what pull rules suggest, and skip the rule lookup for those moves.
    """

    _inherit = "stock.move"

    def _adjust_procure_method(self, picking_type_code=False):
        # pending_ids идва от mrp.production.action_confirm override-а — съдържа
        # MO-тата които ще преминат в 'preparation' СЛЕД като native action_confirm
        # върне. По време на тоя call state-ът е още 'confirmed', затова
        # _staged_intermediate_active() (който чете state == 'preparation') не е
        # достатъчен — нужен е context fallback за initial-confirm race.
        pending_ids = set(self.env.context.get("staged_preparation_pending_ids") or ())
        intermediate_raw = self.filtered(
            lambda m: m.raw_material_production_id
            and (
                m.raw_material_production_id.id in pending_ids
                or m.raw_material_production_id._staged_intermediate_active()
            )
        )
        if intermediate_raw:
            intermediate_raw.procure_method = "make_to_stock"
        remaining = self - intermediate_raw
        if remaining:
            return super(StockMove, remaining)._adjust_procure_method(
                picking_type_code=picking_type_code,
            )
        return None
