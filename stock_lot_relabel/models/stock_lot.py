# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)

import logging

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class StockLot(models.Model):
    _inherit = "stock.lot"

    @api.model
    def _relabel(self, product, qty, location, src_lot, dst_lot, reference):
        """Сменя лота на `qty` от `product` в `location`: `src_lot` → `dst_lot`.

        ⚓ ЛОГИКАТА Е НА ИНВЕНТАРИЗАЦИЯТА (Росен, 29.09): „едното отива на една
        сметка, другото на друга". Две валидирани движения през виртуалната
        локация „Lot Relabel" на фирмата:
          ① `location → Lot Relabel`, лот `src_lot` — изход по FIFO/AVCO/стандарт;
          ② `Lot Relabel → location`, лот `dst_lot` — вход с ТОЧНО стойността на
             изхода (`stock.move._get_in_svl_vals`), до стотинка.
        Двете носят една и съща референция и се сочат взаимно
        (`lot_relabel_pair_id`) — следата се чете от движенията, не от лог.

        🔑 Защо не направо в квантите: едно движение носи ЕДИН лот, а пряката
        смяна в квантите не оставя нито движение, нито слой — лотът „изчезва" и
        „се появява" без следа. Тук всяка смяна е видима в историята на лота.

        ⛔ НЕ `is_inventory`, НЕ брак — количеството и стойността остават;
        сменя се само етикетът.

        ⚠️ Сметките са на локацията (`valuation_in_account_id` за изхода,
        `valuation_out_account_id` за входа). Празни ли са при автоматична
        оценка — отказ. Ядрото тихо би паднало към сметките на категорията.

        Връща двете движения (изход | вход).
        """
        Move = self.env["stock.move"]
        Quant = self.env["stock.quant"]
        company = location.company_id or self.env.company
        rounding = product.uom_id.rounding
        if not product.is_storable:
            raise UserError(_(
                "Only storable products can be relabelled; %(product)s is not.",
                product=product.display_name))
        if not src_lot or not dst_lot or src_lot == dst_lot:
            raise UserError(_(
                "A lot relabel needs two different lots of %(product)s.",
                product=product.display_name))
        if (src_lot | dst_lot).product_id != product:
            raise UserError(_(
                "Lots %(src)s and %(dst)s must both belong to %(product)s.",
                src=src_lot.name, dst=dst_lot.name,
                product=product.display_name))
        if location.usage != "internal":
            raise UserError(_(
                "Stock can be relabelled only in an internal location; "
                "%(location)s is not one.", location=location.display_name))
        if float_compare(qty, 0.0, precision_rounding=rounding) <= 0:
            raise UserError(_("The quantity to relabel must be positive."))
        relabel_loc = company._get_lot_relabel_location()
        if product.with_company(company).valuation == "real_time" and not (
                relabel_loc.valuation_in_account_id
                and relabel_loc.valuation_out_account_id):
            raise UserError(_(
                "The location %(location)s has no incoming or outgoing "
                "valuation account. Set both accounts on it before relabelling "
                "%(product)s, which uses automated inventory valuation.",
                location=relabel_loc.display_name,
                product=product.display_name))
        free = Quant._get_available_quantity(
            product, location, lot_id=src_lot, strict=True)
        if float_compare(free, qty, precision_rounding=rounding) < 0:
            raise UserError(_(
                "Only %(free)s %(uom)s of lot %(lot)s is free in %(location)s; "
                "%(qty)s %(uom)s cannot be relabelled.",
                free=free, qty=qty, uom=product.uom_id.name, lot=src_lot.name,
                location=location.display_name))

        common = {
            "name": reference,
            "origin": reference,
            "product_id": product.id,
            "product_uom": product.uom_id.id,
            "product_uom_qty": qty,
            "company_id": company.id,
            "procure_method": "make_to_stock",
            "lot_relabel_src_lot_id": src_lot.id,
            "lot_relabel_dst_lot_id": dst_lot.id,
        }
        out_move = Move.create(dict(
            common, location_id=location.id,
            location_dest_id=relabel_loc.id, lot_relabel_role="out"))
        self._relabel_done(out_move, src_lot, qty)
        # Цената на входа е производна; истинската стойност влиза през
        # `_get_in_svl_vals` (за FIFO/AVCO цената движи и средната цена).
        out_value = -sum(out_move.sudo().stock_valuation_layer_ids.mapped("value"))
        in_move = Move.create(dict(
            common, location_id=relabel_loc.id,
            location_dest_id=location.id, lot_relabel_role="in",
            lot_relabel_pair_id=out_move.id,
            price_unit=out_value / qty))
        out_move.lot_relabel_pair_id = in_move
        self._relabel_done(in_move, dst_lot, qty)
        _logger.info(
            "Lot relabel %s: %s %s %s → %s в %s, стойност %s",
            reference, qty, product.uom_id.name, src_lot.name, dst_lot.name,
            location.display_name, out_value)
        return out_move | in_move

    @api.model
    def _relabel_done(self, move, lot, qty):
        """Потвърждава и валидира едно движение на преетикетирането с ТОЧНО
        този лот. Редът се пише ръчно — резервацията на ядрото би избрала лот
        сама."""
        move._action_confirm(merge=False)
        # От виртуална локация ядрото резервира още при потвърждението — с ред
        # БЕЗ лот. Махаме всеки такъв ред; остава само нашият.
        move.move_line_ids.unlink()
        self.env["stock.move.line"].create({
            "move_id": move.id,
            "product_id": move.product_id.id,
            "product_uom_id": move.product_uom.id,
            "location_id": move.location_id.id,
            "location_dest_id": move.location_dest_id.id,
            "lot_id": lot.id,
            "quantity": qty,
            "picked": True,
            "company_id": move.company_id.id,
        })
        move.picked = True
        move._action_done()
        if move.state != "done":
            raise UserError(_(
                "The lot relabel move %(move)s could not be validated.",
                move=move.display_name))
