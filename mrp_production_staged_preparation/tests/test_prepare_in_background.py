# -*- coding: utf-8 -*-
"""„Подготви за производство“ е фонова задача (ADR-0098 / ADR-0100, 20.10).

Любо: „фоновите задачи са задължителни, не препоръчителни“. На fulltest
(20.10) 18 МО армировка смятаха разкроя в заявката на браузъра; второто
натискане раждаше втори разкрой (1208/1209 → 1216) и двоен разход.

Тук се пази:
  ① бутонът НЕ смята нищо и няма прозорец (Любо 21.10) — пуска задачата;
    МО-тата са „тече подготовка“; стартът е отделен бутон (⑦);
  ② второ пускане за същите МО-та, докато задачата върви, се отказва;
  ③ свършила / паднала задача не държи МО-то — може да се пусне наново;
  ④ задачата: разкрой → гейт → материализация, после известие и чатър;
    етапът и процентът се виждат като при вноса от ЛогиКал;
  ⑤ отказ на гейта: нищо не остава, МО-то е „Preparation failed“ с причината,
    задачата приключва чисто (не гърми);
  ⑥ един разкрой (Любо 21.10, TG 7298): МО в процес — избрано ИЛИ от стария
    разкрой, който се заменя — ⇒ ПфП се отказва; всички в „Preparation“ ⇒ може;
  ⑦ „Старт на производството“ — само подготвените в „Preparation“: In Progress
    и заключени; неподготвено МО не се стартира оттук.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.queue_job.job import Job

MODEL = "odoo.addons.mrp_production_staged_preparation.models.mrp_production.MrpProduction"


@tagged("post_install", "-at_install")
class TestPrepareInBackground(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        product = cls.env["product.product"].create({
            "name": "T0098 window", "is_storable": True})
        cls.mos = cls.env["mrp.production"].create([
            {"product_id": product.id, "product_qty": 1.0} for _i in range(2)])
        cls.mos.picking_type_id.staged_preparation_enabled = True
        cls.mos.write({"state": "preparation"})

    def _launch(self):
        """ПфП от списъка: без прозорец — задачата тръгва веднага (ADR-0098)."""
        return self.mos.action_prepare_production_batch()

    def _job(self):
        return self.env["queue.job"].search(
            [("uuid", "=", self.mos[:1].staged_prep_job_uuid)])

    def test_button_computes_nothing_and_queues_the_job(self):
        """① Нищо в заявката: нито гейт, нито материализация."""
        with patch(MODEL + "._staged_optimize_and_gate") as gate, \
                patch(MODEL + "._staged_do_prepare") as prepare:
            result = self._launch()
        gate.assert_not_called()
        prepare.assert_not_called()
        self.assertEqual(set(self.mos.mapped("staged_prep_job_state")),
                         {"queued"})
        self.assertFalse(any(self.mos.mapped("staged_released")))
        job = self._job()
        self.assertEqual(job.method_name, "_staged_prepare_job")
        self.assertEqual(job.channel, "root.staged_preparation")
        self.assertEqual(set(self.mos.mapped("staged_prep_job_uuid")),
                         {job.uuid}, "една задача за цялата партида")
        self.assertEqual(result["tag"], "display_notification")

    def test_second_launch_is_refused_while_running(self):
        """② Докато задачата върви, второ пускане се отказва."""
        self._launch()
        with self.assertRaises(UserError):
            self.mos.action_prepare_production_batch()
        with self.assertRaises(UserError):
            self.mos[:1].action_prepare_production()

    def test_a_finished_job_does_not_hold_the_order(self):
        """③ Паднала/свършила задача ⇒ МО-то може да се пусне наново."""
        self._launch()
        self._job().state = "failed"
        self.assertFalse(self.mos._staged_prep_running())
        action = self.mos.action_prepare_production_batch()
        self.assertEqual(action["tag"], "display_notification")

    def test_the_job_prepares_and_tells(self):
        """④ Задачата: гейт → материализация с избора; известие; чатър."""
        self._launch()
        # прогресът се пише със СВОЙ курсор — в тестовия режим на регистъра
        # той минава през същата транзакция и тестът го вижда
        self.registry.enter_test_mode(self.cr)
        self.addCleanup(self.registry.leave_test_mode)
        with patch(MODEL + "._staged_optimize_and_gate") as gate, \
                patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone") as send:
            Job.load(self.env, self._job().uuid).perform()
        gate.assert_called_once()
        prepare.assert_called_once_with(start=False)  # стартът е отделен бутон
        self.assertFalse(any(self.mos.mapped("staged_prep_job_state")))
        self.assertEqual(send.call_args.args[1], "simple_notification")
        self.assertEqual(send.call_args.args[2]["type"], "success")
        self.assertIn("in the background",
                      self.mos[0].message_ids[:1].body or "")
        # като при вноса: етапът и процентът се виждат, докато върви
        self.mos.invalidate_recordset(["staged_prep_progress", "staged_prep_stage"])
        self.assertEqual(self.mos[0].staged_prep_progress, 95)
        self.assertEqual(self.mos[0].staged_prep_stage, "Finishing")

    def test_a_refused_cut_leaves_nothing_and_says_why(self):
        """⑤ Отказ на гейта: материализация няма, причината е на МО-то."""
        self._launch()
        with patch(MODEL + "._staged_optimize_and_gate",
                   side_effect=UserError("A326: short 140 m")), \
                patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone") as send:
            Job.load(self.env, self._job().uuid).perform()
        prepare.assert_not_called()
        self.assertEqual(set(self.mos.mapped("staged_prep_job_state")),
                         {"failed"})
        self.assertEqual(self.mos[0].staged_prep_error, "A326: short 140 m")
        self.assertEqual(send.call_args.args[2]["type"], "danger")
        # паднала ⇒ не държи — пуска се наново
        self.assertFalse(self.mos._staged_prep_running())

    def _old_run_with(self, other_state):
        """Старият разкрой носи mos[0] и трето МО в даденото състояние."""
        other = self.env["mrp.production"].create({
            "product_id": self.mos[0].product_id.id, "product_qty": 1.0})
        other.write({"state": other_state})
        opt = self.env["mrp.cutting.optimization"].create({
            "name": "T0100 old run", "material_domain": "mrp_production",
            "production_ids": [(6, 0, (self.mos[0] | other).ids)]})
        self.mos[0].staged_cutting_optimization_id = opt
        return other

    def test_an_order_in_process_on_the_old_run_refuses(self):
        """⑥ M002315 в процес на 1209 ⇒ повторна ПфП на M002309 — отказ."""
        other = self._old_run_with("progress")
        with self.assertRaises(UserError) as err:
            self.mos[:1].action_prepare_production()
        self.assertIn(other.name, str(err.exception))
        with self.assertRaises(UserError):
            self.mos.action_prepare_production_batch()

    def test_all_in_preparation_may_be_recut(self):
        """⑥ Контрола: старият разкрой е само с МО-та в „Preparation“ ⇒ може."""
        self._old_run_with("preparation")
        action = self.mos[:1].action_prepare_production()
        self.assertEqual(action["tag"], "display_notification")

    def test_start_is_a_separate_step(self):
        """⑦ Стартът: само подготвеното, после In Progress и заключено."""
        with self.assertRaises(UserError):
            self.mos.action_staged_start()  # още не е подготвено
        self.mos.write({"staged_released": True})
        self.mos.action_staged_start()
        self.assertEqual(set(self.mos.mapped("state")), {"progress"})
        self.assertTrue(all(self.mos.mapped("is_locked")))
