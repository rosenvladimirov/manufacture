# Copyright 2025 Your Company
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        """При потвърждаване — и ръчните редове за прът без лот се казват (№118 т.2).

        Тест 02.10 (Клаудио, fulltest, P00208): ръчен ред за прът по лот без
        форсиран лот — бележка НЕ се появи, защото предпазителят седеше само по
        пътя на правилото за попълване. Потвърждаването е мястото, през което
        минава всеки ред — от правилото, от МО-то и на ръка. Продукт, за който
        бележката вече е писана (при раждането на реда от правилото), не се
        казва втори път.
        """
        Line = self.env["purchase.order.line"]
        for po in self:
            for product in po.order_line.filtered(
                    lambda l: l.product_id and not l.forced_lot_ids
                    and not l.display_type).product_id:
                Line._forced_lot_note_missing(product, po, on_confirm=True)
        return super().button_confirm()
