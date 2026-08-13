#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from collections import defaultdict

from odoo import models
from odoo.tools.float_utils import float_round

_logger = logging.getLogger(__name__)


class MRPProduction(models.Model):
    _inherit = "mrp.production"

    def _get_move_raw_values(
        self,
        product,
        product_uom_qty,
        product_uom,
        operation_id=False,
        bom_line=False,
    ):
        _logger.info(
            "=== _get_move_raw_values CALLED === "
            "MO=%s, product=%s (id=%s), original_qty=%s, uom=%s, "
            "bom_line=%s (id=%s), bom_line.loss=%s",
            self.name,
            product.display_name,
            product.id,
            product_uom_qty,
            product_uom.name,
            bom_line.display_name if bom_line else False,
            bom_line.id if bom_line else False,
            bom_line.loss if bom_line else 'N/A',
        )

        if bom_line and bom_line.loss:
            factor = 1.0 + bom_line.loss
            _logger.info(
                "  -> loss=%s, factor=%s, qty BEFORE=%s, qty AFTER=%s",
                bom_line.loss, factor, product_uom_qty,
                product_uom_qty * factor if factor > 0.0 else product_uom_qty,
            )
            if factor > 0.0:
                # bom.explode() закръгля product_uom_qty до UoM precision
                # ПРЕДИ loss; при гранични стойности (5.765 -> 5.77) това
                # x loss дава грешен резултат (6.015 вместо 6.010).
                # Реконструираме незакръгленото net от bom_line и прилагаме
                # loss + закръгляне в правилен ред: round(net x factor).
                rounding = (product_uom or product.uom_id).rounding or 0.01
                base = bom_line.product_qty or 0.0
                net_qty = product_uom_qty
                if base > 0:
                    units = round(product_uom_qty / base)
                    if units >= 1 and abs(product_uom_qty - base * units) <= rounding:
                        net_qty = base * units
                product_uom_qty = float_round(net_qty * factor, precision_rounding=rounding)
        else:
            _logger.info(
                "  -> NO LOSS APPLIED (bom_line=%s, bom_line.loss=%s)",
                bool(bom_line),
                bom_line.loss if bom_line else 'N/A',
            )

        result = super()._get_move_raw_values(
            product,
            product_uom_qty,
            product_uom,
            operation_id=operation_id,
            bom_line=bom_line,
        )
        _logger.info(
            "  -> FINAL move values: product_uom_qty=%s",
            result.get('product_uom_qty'),
        )
        return result

    def _link_bom(self, bom):
        """Override to apply loss factor when updating MO from BoM."""
        self.ensure_one()

        # Call super first to handle all the BoM linking logic
        res = super()._link_bom(bom)

        # After linking, apply loss factor to all move_raw quantities
        if self.state not in ['cancel', 'done', 'draft']:
            ratio = self._get_ratio_between_mo_and_bom_quantities(bom)
            for move_raw in self.move_raw_ids:
                if move_raw.bom_line_id and move_raw.bom_line_id.loss:
                    factor = 1.0 + move_raw.bom_line_id.loss
                    if factor > 0.0:
                        # Get the base quantity from bom_line
                        _dummy, bom_lines = bom.explode(self.product_id, bom.product_qty)
                        for line, exploded_values in bom_lines:
                            if line.id == move_raw.bom_line_id.id:
                                base_qty = exploded_values['qty'] / ratio
                                # Apply loss factor
                                move_raw.product_uom_qty = base_qty * factor
                                _logger.info(
                                    "_link_bom: Applied loss=%s to move=%s, base_qty=%s, final_qty=%s",
                                    move_raw.bom_line_id.loss, move_raw.product_id.display_name,
                                    base_qty, move_raw.product_uom_qty
                                )
                                break

        return res
2