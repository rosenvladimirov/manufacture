# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)

from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    # 🔑 Втората сметка на преетикетирането (решение на Росен — две сметки,
    # както в 18). В 18 локацията имаше две: `valuation_in_account_id` (Дт при
    # изхода към нея) и `valuation_out_account_id` (Кт при входа от нея). В 19
    # ядрото остави една — `valuation_account_id`, — и тя носи изхода. Това
    # поле носи входа: Кт на входящото движение на преетикетирането (ролята
    # „in"). „out" в името е от гледна точка на ЛОКАЦИЯТА — стоката излиза
    # от нея обратно в склада, — както `valuation_out_account_id` в 18.
    # Чете го само преетикетирането (`stock.move._get_account_move_line_vals`);
    # за другите движения от локацията ядрото остава с едната сметка.
    # ETL: 18 `stock_location.valuation_out_account_id` → това поле.
    lot_relabel_out_account_id = fields.Many2one(
        "account.account",
        string="Lot Relabel Return Account",
        domain=[("account_type", "not in", (
            "asset_receivable", "liability_payable", "asset_cash",
            "liability_credit_card"))],
        help="Credited when stock comes back from this location with the "
             "target lot of a lot relabel. The stock valuation account is "
             "debited when the stock leaves with the source lot. Both are "
             "required for products with perpetual inventory valuation.",
    )
    is_lot_relabel_location = fields.Boolean(
        string="Is Lot Relabel Location",
        compute="_compute_is_lot_relabel_location")

    def _compute_is_lot_relabel_location(self):
        relabel_locs = self.env["res.company"].sudo().search(
            []).lot_relabel_location_id
        for location in self:
            location.is_lot_relabel_location = location in relabel_locs
