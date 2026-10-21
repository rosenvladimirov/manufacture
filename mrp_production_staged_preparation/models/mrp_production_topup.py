# -*- coding: utf-8 -*-
# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
"""Допълването на разкроя (ADR-0099, Любо 20.10 / 21.10, TG 173295 / 173297).

Остатъците на прътите в разкроя за одобрение се пълнят с вариантите на СЪЩИЯ
артикул, които имат точка за поръчка с Max > 0 — най-късите първо, докато в
модела има място за още едно парче (дължина + рез), най-много до Max −
прогнозната наличност. Задача А само ПРЕДЛАГА (редове тук); човекът ги вижда
в екрана за одобрение, може да ги редактира, а „Да, с допълването“ ги прилага
в задача Б: увеличава МО-то на варианта в разкроя или създава ново МО за
склад, разкроява наново и подготвя.
"""
import logging
import math
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_LENGTH_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*mm", re.IGNORECASE)


class MrpProductionTopup(models.Model):
    _name = "mrp.production.topup"
    _description = "Cutting Top-up Proposal"
    _order = "cut_mm, id"

    optimization_id = fields.Many2one(
        "mrp.cutting.optimization", string="Cutting Run",
        required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", string="Article", required=True)
    production_id = fields.Many2one(
        "mrp.production", string="Into Order",
        help="The order of this article in the cutting run; empty — a new "
             "order for stock is created.")
    block_qty = fields.Float(
        "Units per Piece", default=1.0,
        help="Units cut together in one piece (a bundle of 12 bars gives 12).")
    qty = fields.Float("Quantity")
    cut_mm = fields.Float("Cut Length (mm)")
    max_qty = fields.Float("Max")
    forecast_qty = fields.Float("Forecast")
    over_max = fields.Float(
        "Over Max", compute="_compute_over_max",
        help="Units above the reordering rule's Max after the top-up.")

    @api.depends("qty", "max_qty", "forecast_qty")
    def _compute_over_max(self):
        for line in self:
            line.over_max = max(0.0, line.forecast_qty + line.qty - line.max_qty)

    @api.constrains("qty", "block_qty")
    def _check_blocks(self):
        for line in self:
            if line.qty < 0:
                raise ValidationError(_("The top-up quantity cannot be negative."))
            if line.block_qty > 0 and abs(line.qty / line.block_qty - round(line.qty / line.block_qty)) > 1e-6:
                raise ValidationError(_(
                    "%(article)s: the top-up goes in whole pieces of %(step)s.",
                    article=line.product_id.display_name, step=line.block_qty))


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    # ── сметката (задача А) ──────────────────────────────────────────────

    @staticmethod
    def _staged_variant_length(product):
        """Дължината на варианта от атрибута му („300 mm“) или None."""
        for ptav in product.product_template_attribute_value_ids:
            match = _LENGTH_RE.search(ptav.name or "")
            if match:
                return float(match.group(1).replace(",", "."))
        return None

    def _staged_compute_topups(self, opt):
        """Предложението за допълване на разкроя ``opt`` — НИЩО не създава."""
        Topup = self.env["mrp.production.topup"]
        Topup.search([("optimization_id", "=", opt.id)]).unlink()
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        Piece = self.env.get("mrp.cutting.piece")
        if Piece is None or not opt.pattern_ids:
            return Topup

        # Вариантите в разкроя: дължина на рязане и броят в парче, по шаблон.
        known = {}  # product → (cut_mm, block_qty, MO)
        delta = {}  # шаблон → номинал − рязане (MD 101: парче −2 мм)
        for mo in self:
            pieces = mo.cutting_piece_ids.filtered(lambda p: p.length_mm > 0)
            if not pieces:
                continue
            cut = max(pieces.mapped("length_mm"))
            count = sum(pieces.mapped("quantity")) or len(pieces)
            block = mo.product_qty / count if count else 1.0
            known.setdefault(mo.product_id, (cut, block, mo))
            nominal = self._staged_variant_length(mo.product_id)
            if nominal is not None:
                delta.setdefault(mo.product_id.product_tmpl_id, (nominal - cut, block))

        # Кандидатите: вариантите на същите шаблони с точка за поръчка Max > 0.
        candidates = []
        for tmpl, (diff, block) in delta.items():
            for variant in tmpl.product_variant_ids:
                rule = Orderpoint.search([
                    ("product_id", "=", variant.id), ("product_max_qty", ">", 0)], limit=1)
                if not rule:
                    continue
                if variant in known:
                    cut, vblock, mo = known[variant]
                else:
                    nominal = self._staged_variant_length(variant)
                    if nominal is None:
                        continue
                    cut, vblock, mo = nominal - diff, block, False
                step = max(vblock, rule.qty_multiple or 0.0) or 1.0
                room = rule.product_max_qty - rule.qty_forecast
                room_pieces = int(math.floor(room / vblock + 1e-9)) if vblock else 0
                # кратното на точката за поръчка — в цели парчета
                per = max(1, int(round(step / vblock))) if vblock else 1
                room_pieces -= room_pieces % per
                if room_pieces <= 0:
                    continue
                candidates.append({
                    "product": variant, "cut": cut, "block": vblock, "mo": mo,
                    "room": room_pieces, "per": per, "rule": rule, "taken": 0,
                })
        if not candidates:
            return Topup
        candidates.sort(key=lambda c: c["cut"])

        # Пълненето: за всеки физически прът, най-късите първо.
        for pattern in opt.pattern_ids.sorted("id"):
            kerf = pattern.kerf_mm or 0.0
            for _bar in range(int(pattern.usage_count or 0)):
                free = pattern.remnant_length or 0.0
                for cand in candidates:
                    need = cand["cut"] + kerf
                    if need <= 0:
                        continue
                    fit = int(math.floor(free / need + 1e-9))
                    take = min(fit, cand["room"] - cand["taken"])
                    if take <= 0:
                        continue
                    cand["taken"] += take
                    free -= take * need
        lines = []
        for cand in candidates:
            pieces = cand["taken"] - cand["taken"] % cand["per"]
            if pieces <= 0:
                continue
            lines.append({
                "optimization_id": opt.id,
                "product_id": cand["product"].id,
                "production_id": cand["mo"].id if cand["mo"] else False,
                "block_qty": cand["block"],
                "qty": pieces * cand["block"],
                "cut_mm": cand["cut"],
                "max_qty": cand["rule"].product_max_qty,
                "forecast_qty": cand["rule"].qty_forecast,
            })
        return Topup.create(lines)

    # ── прилагането (задача Б) ───────────────────────────────────────────

    def _staged_apply_topups(self, topups):
        """„Да, с допълването“: МО на варианта се увеличава, иначе ново МО.

        Връща новите МО-та — влизат в разкроя заедно с останалите.
        """
        new = self.env["mrp.production"]
        template = self[:1]
        for line in topups.filtered(lambda t: t.qty > 0):
            mo = line.production_id
            if mo and mo.state == "preparation" and not mo.staged_released:
                self.env["change.production.qty"].create({
                    "mo_id": mo.id, "product_qty": mo.product_qty + line.qty,
                }).change_prod_qty()
                mo.message_post(body=_(
                    "Cutting top-up: +%(qty)s %(uom)s from the remnants of %(run)s.",
                    qty=line.qty, uom=mo.product_uom_id.name, run=line.optimization_id.name))
                continue
            order = self.create({
                "product_id": line.product_id.id,
                "product_qty": line.qty,
                "product_uom_id": line.product_id.uom_id.id,
                "picking_type_id": template.picking_type_id.id,
                "origin": _("Top-up %s", line.optimization_id.name),
            })
            order.action_confirm()
            if order.state == "confirmed":
                order.button_plan()
            order.message_post(body=_(
                "Created to top up the cutting run %s from its remnants.",
                line.optimization_id.name))
            new |= order
        return new
