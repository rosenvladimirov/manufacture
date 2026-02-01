#  Copyright 2026 vladimirov.rosen@gmail.com
#  License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, models


class ReportBomStructure(models.AbstractModel):
    _inherit = "report.mrp.report_bom_structure"

    @api.model
    def _get_component_data(
        self,
        parent_bom,
        parent_product,
        warehouse,
        bom_line,
        line_quantity,
        level,
        index,
        product_info,
        ignore_stock=False,
    ):
        res = super()._get_component_data(
            parent_bom,
            parent_product,
            warehouse,
            bom_line,
            line_quantity,
            level,
            index,
            product_info,
            ignore_stock=ignore_stock,
        )
        res["line_id"] = bom_line.id
        res["distribution_coefficient"] = bom_line.distribution_coefficient or 0.0
        res["is_distribution_master"] = bom_line.is_distribution_master
        base_qty = 0.0
        if bom_line.product_qty:
            base_qty = bom_line.bom_id.base_distribution_qty * (
                line_quantity / bom_line.product_qty
            )
        res["distribution_base_qty"] = base_qty
        res["qty_with_distribution"] = line_quantity
        return res

    @api.model
    def _get_bom_array_lines(
        self, data, level, unfolded_ids, unfolded, parent_unfolded=True
    ):
        bom_lines = data["components"]
        lines = []
        for bom_line in bom_lines:
            line_unfolded = ("bom_" + str(bom_line["index"])) in unfolded_ids
            line_visible = level == 1 or unfolded or parent_unfolded
            lines.append(
                {
                    "bom_id": bom_line["bom_id"],
                    "name": bom_line["name"],
                    "type": bom_line["type"],
                    "quantity": bom_line["quantity"],
                    "quantity_available": bom_line["quantity_available"],
                    "quantity_on_hand": bom_line["quantity_on_hand"],
                    "producible_qty": bom_line.get("producible_qty", False),
                    "uom": bom_line["uom_name"],
                    "prod_cost": bom_line["prod_cost"],
                    "bom_cost": bom_line["bom_cost"],
                    "distribution_coefficient": bom_line.get(
                        "distribution_coefficient", 0.0
                    ),
                    "distribution_base_qty": bom_line.get("distribution_base_qty", 0.0),
                    "qty_with_distribution": bom_line.get(
                        "qty_with_distribution", bom_line["quantity"]
                    ),
                    "route_name": bom_line["route_name"],
                    "route_detail": bom_line["route_detail"],
                    "route_alert": bom_line.get("route_alert", False),
                    "lead_time": bom_line["lead_time"],
                    "manufacture_delay": bom_line["manufacture_delay"],
                    "level": bom_line["level"],
                    "code": bom_line["code"],
                    "availability_state": bom_line["availability_state"],
                    "availability_display": bom_line["availability_display"],
                    "visible": line_visible,
                }
            )
            if bom_line.get("components"):
                lines += self._get_bom_array_lines(
                    bom_line,
                    level + 1,
                    unfolded_ids,
                    unfolded,
                    line_visible and line_unfolded,
                )

        if data["operations"]:
            lines.append(
                {
                    "name": _("Operations"),
                    "type": "operation",
                    "quantity": data["operations_time"],
                    "uom": _("minutes"),
                    "bom_cost": data["operations_cost"],
                    "level": level,
                    "visible": parent_unfolded,
                }
            )
            operations_unfolded = unfolded or (
                parent_unfolded and ("operations_" + str(data["index"])) in unfolded_ids
            )
            for operation in data["operations"]:
                lines.append(
                    {
                        "name": operation["name"],
                        "type": "operation",
                        "quantity": operation["quantity"],
                        "uom": "minutes",
                        "bom_cost": operation["bom_cost"],
                        "level": level + 1,
                        "availability_state": operation["availability_state"],
                        "availability_delay": operation["availability_delay"],
                        "availability_display": operation["availability_display"],
                        "visible": operations_unfolded,
                    }
                )
        if data["byproducts"]:
            lines.append(
                {
                    "name": _("Byproducts"),
                    "type": "byproduct",
                    "uom": False,
                    "quantity": data["byproducts_total"],
                    "bom_cost": data["byproducts_cost"],
                    "level": level,
                    "visible": parent_unfolded,
                }
            )
            byproducts_unfolded = unfolded or (
                parent_unfolded and ("byproducts_" + str(data["index"])) in unfolded_ids
            )
            for byproduct in data["byproducts"]:
                lines.append(
                    {
                        "name": byproduct["name"],
                        "type": "byproduct",
                        "quantity": byproduct["quantity"],
                        "uom": byproduct["uom_name"],
                        "prod_cost": byproduct["prod_cost"],
                        "bom_cost": byproduct["bom_cost"],
                        "level": level + 1,
                        "visible": byproducts_unfolded,
                    }
                )
        return lines
