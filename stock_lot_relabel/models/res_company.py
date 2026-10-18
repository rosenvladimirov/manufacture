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
             "its stock valuation account before the first relabel of a "
             "product with perpetual valuation.",
    )

    def _create_per_company_locations(self):
        res = super()._create_per_company_locations()
        self._get_lot_relabel_location()
        return res

    def _get_lot_relabel_location(self):
        """Виртуалната локация „Lot Relabel" на фирмата — ражда я, ако липсва.

        🔑 Като „Inventory adjustment": usage `inventory`, вързана за фирмата.
        В 19 родителят „Virtual Locations" вече го няма (ядрото ражда и
        локацията на инвентаризацията без родител) — и тук е без родител.
        Но НЕ същата локация: сметката на инвентаризацията е за липси и
        излишъци, а преетикетирането не е нито едното — количеството и
        стойността остават, сменя се само лотът.

        ⚠️ Сметката (`valuation_account_id`; в 19 тя е ЕДНА — в 18 бяха две,
        входяща и изходяща) се оставя ПРАЗНА нарочно — избира я
        счетоводителят при внедряването. Празна ли е при продукт с
        перманентна оценка, `stock.lot._relabel` отказва; ядрото в 19 тихо
        би пропуснало счетоводния запис.
        """
        self.ensure_one()
        location = self.sudo().lot_relabel_location_id
        if location:
            return location
        location = self.env["stock.location"].sudo().create({
            "name": "Lot Relabel",
            "usage": "inventory",
            "company_id": self.id,
        })
        self.sudo().lot_relabel_location_id = location
        return location
