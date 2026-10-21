# -*- coding: utf-8 -*-
"""Допълването на разкроя (ADR-0099, Любо 20.10 / 21.10, TG 173295 / 173297).

Сценарият е пробата на Клаудио на fulltest: снопът A226 (12 × 6000), M002324
(240 × 300 мм, режат се 298) + M002325 (36 × 1800, режат се 1798), срез 2 мм.
Моделът с двата 1800 оставя 600 мм ⇒ 2 парчета по 300 (298 + 2) ⇒ +24 бр.
Точката за поръчка на 300 мм: Max 288, кратно 12, прогнозна 240 ⇒ място 48.

Тук се пази:
  ① предложението: вариантът с Max > 0, в цели парчета, към МО-то му;
  ② спирачката — най-много до Max − прогнозната; на/над Max — нищо;
  ③ вариант без точка за поръчка (Max 0) не се предлага;
  ④ задача А само предлага — нищо не създава, количеството на МО не мърда;
  ⑤ екранът: редовете се виждат и редактират (в цели парчета), над Max —
    предупреждение; „Без допълване“ ги маха;
  ⑥ „Да, с допълването“: МО-то на варианта се увеличава; вариант без МО в
    разкроя → ново МО за склад.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

MODEL = "odoo.addons.mrp_production_staged_preparation.models.mrp_production.MrpProduction"


@tagged("post_install", "-at_install")
class TestCuttingTopup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        attr = cls.env["product.attribute"].create({
            "name": "Length T0099", "create_variant": "always",
            "value_ids": [(0, 0, {"name": "300 mm"}), (0, 0, {"name": "1800 mm"}),
                          (0, 0, {"name": "600 mm"})]})
        cls.tmpl = cls.env["product.template"].create({
            "name": "Reinforcement T0099", "is_storable": True,
            "attribute_line_ids": [(0, 0, {"attribute_id": attr.id,
                                           "value_ids": [(6, 0, attr.value_ids.ids)]})]})
        by_len = {v.product_template_attribute_value_ids.name: v
                  for v in cls.tmpl.product_variant_ids}
        cls.v300, cls.v1800, cls.v600 = by_len["300 mm"], by_len["1800 mm"], by_len["600 mm"]
        cls.bar = cls.env["product.product"].create({"name": "Bundle T0099", "is_storable": True})
        cls.mo300 = cls._mo(cls.v300, 240, 298, 20)
        cls.mo1800 = cls._mo(cls.v1800, 36, 1798, 3)
        cls.mos = cls.mo300 | cls.mo1800
        cls.opt = cls.env["mrp.cutting.optimization"].create({
            "name": "T0099 cut", "material_domain": "mrp_production"})
        Pattern = cls.env["mrp.cutting.pattern"]
        Pattern.create({"optimization_id": cls.opt.id, "name": "P1", "usage_count": 1,
                        "bar_capacity_mm": 6000, "remnant_length": 0, "kerf_mm": 2,
                        "cuts_json": '{"298.00": 14, "1798.00": 1}', "bar_product_id": cls.bar.id})
        Pattern.create({"optimization_id": cls.opt.id, "name": "P2", "usage_count": 1,
                        "bar_capacity_mm": 6000, "remnant_length": 600, "kerf_mm": 2,
                        "cuts_json": '{"298.00": 6, "1798.00": 2}', "bar_product_id": cls.bar.id})
        cls.mos.write({"staged_cutting_optimization_id": cls.opt.id})
        wh = cls.env["stock.warehouse"].search([], limit=1)
        cls.rule = cls.env["stock.warehouse.orderpoint"].create({
            "product_id": cls.v300.id, "warehouse_id": wh.id, "location_id": wh.lot_stock_id.id,
            "product_min_qty": 0, "product_max_qty": 288, "qty_multiple": 12})

    @classmethod
    def _mo(cls, product, qty, cut, pieces):
        mo = cls.env["mrp.production"].create({"product_id": product.id, "product_qty": qty})
        mo.cutting_piece_ids.unlink()
        cls.env["mrp.cutting.piece"].create([
            {"production_id": mo.id, "product_id": cls.bar.id, "length_mm": cut, "quantity": 1}
            for _i in range(pieces)])
        return mo

    def _forecast(self, value):
        return patch.object(type(self.rule), "qty_forecast", value)

    def _topups(self, forecast=240):
        with patch.object(type(self.env["stock.warehouse.orderpoint"]), "_compute_qty",
                          lambda rules: [setattr(r, "qty_forecast", forecast) or setattr(r, "qty_to_order", 0) for r in rules]):
            return self.mos._staged_compute_topups(self.opt)

    def test_proposal_fills_the_remnant_into_the_variant_order(self):
        """① +24 бр. 300 мм (2 парчета × 12) към M002324."""
        lines = self._topups()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.product_id, self.v300)
        self.assertEqual(lines.qty, 24)
        self.assertEqual(lines.block_qty, 12)
        self.assertEqual(lines.production_id, self.mo300)

    def test_the_brake_is_max_minus_forecast(self):
        """② Място 12 ⇒ +12 (едно парче); на Max ⇒ нищо."""
        self.assertEqual(self._topups(forecast=276).qty, 12)
        self.assertFalse(self._topups(forecast=288))

    def test_a_variant_without_max_is_not_proposed(self):
        """③ 1800 (без точка за поръчка) и 600 (без Max) не се предлагат."""
        lines = self._topups()
        self.assertNotIn(self.v1800, lines.product_id)
        self.assertNotIn(self.v600, lines.product_id)

    def test_job_a_only_proposes(self):
        """④ Предложението не мени МО-тата и не създава нови."""
        before = self.env["mrp.production"].search_count([])
        self._topups()
        self.assertEqual(self.mo300.product_qty, 240)
        self.assertEqual(self.env["mrp.production"].search_count([]), before)

    def test_the_screen_shows_and_edits_the_top_up(self):
        """⑤ Редовете в екрана; редакция в цели парчета; над Max — предупреждение."""
        line = self._topups()
        wiz = self.env["mrp.production.prepare.wizard"].create(
            {"production_ids": [(6, 0, self.mos.ids)]})
        self.assertEqual(wiz.topup_ids, line)
        self.assertGreater(wiz.waste_without_pct, wiz.waste_with_pct)
        wiz.write({"topup_ids": [(1, line.id, {"qty": 60})]})
        self.assertEqual(line.qty, 60, "редакцията в екрана не стигна до реда")
        self.assertEqual(line.over_max, 12)
        with self.assertRaises(ValidationError):
            line.qty = 30  # не е цяло парче от 12

    def test_yes_with_top_up_grows_the_order_or_creates_one(self):
        """⑥ МО-то на 300 расте с 24; вариант без МО → ново МО за склад."""
        line = self._topups()
        extra = line.copy({"product_id": self.v600.id, "production_id": False,
                           "qty": 12, "cut_mm": 598})
        self.mos.write({"state": "preparation"})
        with patch.object(type(self.env["mrp.production"]), "button_plan", lambda mos: mos.write({"state": "preparation"})):
            new = self.mos._staged_apply_topups(line | extra)
        self.assertEqual(self.mo300.product_qty, 264)
        self.assertEqual(new.product_id, self.v600)
        self.assertEqual(new.product_qty, 12)
