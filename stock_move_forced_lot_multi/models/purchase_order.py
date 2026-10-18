# Copyright 2025-2026 Rosen Vladimirov
#
# This file is available under a DUAL LICENSE:
#   1. GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
#      https://www.gnu.org/licenses/agpl-3.0.html
#   2. A commercial license from Rosen Vladimirov, for use without the obligations
#      of the AGPL. See LICENSE-COMMERCIAL.md. Contact: vladimirov.rosen@gmail.com
#
# Unless you hold a valid commercial license, your use of this file is governed
# by the AGPL-3.0-or-later.

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
                lambda line: line.product_id
                and not line.forced_lot_ids
                and not line.display_type
            ).product_id:
                Line._forced_lot_note_missing(product, po, on_confirm=True)
        return super().button_confirm()
