# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    lot_relabel_location_id = fields.Many2one(
        "stock.location",
        string="Lot Relabel Location",
        help="Virtual location through which stock changes its lot in place: "
             "it leaves with the old lot and comes back with the new one. Set "
             "its incoming and outgoing valuation accounts before the first "
             "relabel of a product with automated valuation.",
    )

    def _create_per_company_locations(self):
        res = super()._create_per_company_locations()
        self._get_lot_relabel_location()
        return res

    def _get_lot_relabel_location(self):
        """Виртуалната локация „Lot Relabel" на фирмата — ражда я, ако липсва.

        🔑 Като „Virtual Locations / Inventory adjustment": usage `inventory`,
        вързана за фирмата, под виртуалните локации. Но НЕ същата: сметките на
        инвентаризацията са за липси и излишъци, а преетикетирането не е нито
        едното — количеството и стойността остават, сменя се само лотът.

        ⚠️ Сметките се оставят ПРАЗНИ нарочно — избира ги счетоводителят при
        внедряването. Празни ли са при продукт с автоматична оценка,
        `stock.lot._relabel` отказва; не пада тихо към сметките на категорията.
        """
        self.ensure_one()
        location = self.sudo().lot_relabel_location_id
        if location:
            return location
        parent = self.env.ref(
            "stock.stock_location_locations_virtual", raise_if_not_found=False)
        location = self.env["stock.location"].sudo().create({
            "name": "Lot Relabel",
            "usage": "inventory",
            "location_id": parent.id if parent else False,
            "company_id": self.id,
        })
        self.sudo().lot_relabel_location_id = location
        return location
