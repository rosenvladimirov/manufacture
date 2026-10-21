# -*- coding: utf-8 -*-
"""„Подготви за производство“: разкроят → одобрение → подготовка (ADR-0098 / ADR-0100).

Любо: „фоновите задачи са задължителни, не препоръчителни“ (20.10) и
„Натискаш ПфП, започва оптимизация, изчислява всичко, дава ми разкроя и
обобщените данни, пита ме дали одобрявам този разкрой и чак като кажа да
започва да пише и да стартира позициите“ (21.10, TG 173286).

Тук се пази:
  ① бутонът НЕ смята нищо — пуска задача А; МО-тата са „тече разкроят“;
  ② второ пускане, докато задачата върви, се отказва;
  ③ свършила / паднала задача не държи МО-то — може да се пусне наново;
  ④ задача А: само разкроят (без резервация, без материализация) →
    „Cutting awaits approval“, известие, бележка; етап и процент като при вноса;
  ⑤ отказ на гейта: нищо не остава, „Preparation failed“ с причината;
  ⑥ един разкрой (Любо 21.10, TG 7298): МО в процес — избрано ИЛИ от стария
    разкрой — ⇒ ПфП се отказва; всички в „Preparation“ ⇒ може;
  ⑦ „Старт на производството“ — само подготвените в „Preparation“;
  ⑧ „Да“ → задача Б: материализация и старт; „Не“ → разкроят се маха, нищо
    не остава; докато чака одобрение — ново ПфП се отказва.
"""
import logging
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
        """ПфП от списъка: без прозорец — задача А тръгва веднага."""
        return self.mos.action_prepare_production_batch()

    def _job(self):
        return self.env["queue.job"].search(
            [("uuid", "=", self.mos[:1].staged_prep_job_uuid)])

    def _perform(self):
        Job.load(self.env, self.mos[:1].staged_prep_job_uuid).perform()

    def _cut(self):
        """Задача А с подменен гейт — оставя разкрой „за одобрение“."""
        self._launch()
        opt = self.env["mrp.cutting.optimization"].create({
            "name": "T0098 cut", "material_domain": "mrp_production"})

        def gate(mos):
            mos.write({"staged_cutting_optimization_id": opt.id})
            # като разкроя на живо (M002321, 21.10): предупреждение в лога
            logging.getLogger("odoo.addons.cutting_plugin_t0098").warning(
                "Saw '' has no mrp.saw.format mapping")
            return opt
        with patch(MODEL + "._staged_optimize_and_gate", autospec=True,
                   side_effect=gate), \
                patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            self._perform()
        prepare.assert_not_called()
        return opt

    def test_button_computes_nothing_and_queues_the_job(self):
        """① Нищо в заявката: нито гейт, нито материализация."""
        with patch(MODEL + "._staged_optimize_and_gate") as gate, \
                patch(MODEL + "._staged_do_prepare") as prepare:
            result = self._launch()
        gate.assert_not_called()
        prepare.assert_not_called()
        self.assertEqual(set(self.mos.mapped("staged_prep_job_state")), {"queued"})
        self.assertFalse(any(self.mos.mapped("staged_released")))
        job = self._job()
        self.assertEqual(job.method_name, "_staged_prepare_job")
        self.assertEqual(job.channel, "root.staged_preparation")
        self.assertEqual(set(self.mos.mapped("staged_prep_job_uuid")), {job.uuid},
                         "една задача за цялата партида")
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
        self.assertEqual(self.mos.action_prepare_production_batch()["tag"],
                         "display_notification")

    def test_job_a_only_cuts_and_waits_for_approval(self):
        """④ Задача А: разкроят без резервация; чака одобрение; известие, бележка."""
        self._launch()
        self.registry.enter_test_mode(self.cr)
        self.addCleanup(self.registry.leave_test_mode)
        with patch(MODEL + "._staged_optimize_and_gate", return_value=False) as gate, \
                patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone") as send:
            self._perform()
        gate.assert_called_once()
        self.assertTrue(gate.call_args is not None)
        prepare.assert_not_called()
        self.assertEqual(set(self.mos.mapped("staged_prep_job_state")), {"awaiting"})
        self.assertFalse(any(self.mos.mapped("staged_released")))
        # TG 173291: известието с бутон „Одобри“ / формата сама — по шината
        ready = [c.args for c in send.call_args_list if c.args[1] == "staged_cut_ready"]
        self.assertEqual(len(ready), 1)
        self.assertEqual(sorted(ready[0][2]["production_ids"]), sorted(self.mos.ids))
        self.assertIn("awaits approval", self.mos[0].message_ids[:1].body or "")
        self.mos.invalidate_recordset(["staged_prep_progress", "staged_prep_stage"])
        self.assertEqual(self.mos[0].staged_prep_progress, 95)
        self.assertEqual(self.mos[0].staged_prep_stage, "Finishing")

    def test_job_a_cuts_without_reserving(self):
        """④ Разкроят за одобрение носи `cut_allocation_no_assign`."""
        self._launch()
        seen = {}

        def gate(mos):
            seen["no_assign"] = mos.env.context.get("cut_allocation_no_assign")
        with patch(MODEL + "._staged_optimize_and_gate", autospec=True,
                   side_effect=gate), \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            self._perform()
        self.assertTrue(seen.get("no_assign"))

    def test_a_refused_cut_leaves_nothing_and_says_why(self):
        """⑤ Отказ на гейта: материализация няма, причината е на МО-то."""
        self._launch()
        with patch(MODEL + "._staged_optimize_and_gate",
                   side_effect=UserError("A326: short 140 m")), \
                patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone") as send:
            self._perform()
        prepare.assert_not_called()
        self.assertEqual(set(self.mos.mapped("staged_prep_job_state")), {"failed"})
        self.assertEqual(self.mos[0].staged_prep_error, "A326: short 140 m")
        self.assertEqual(send.call_args.args[2]["type"], "danger")
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
        self.assertEqual(self.mos[:1].action_prepare_production()["tag"],
                         "display_notification")

    def test_start_is_a_separate_step(self):
        """⑦ Стартът: само подготвеното, после In Progress и заключено."""
        with self.assertRaises(UserError):
            self.mos.action_staged_start()  # още не е подготвено
        self.mos.write({"staged_released": True})
        self.mos.action_staged_start()
        self.assertEqual(set(self.mos.mapped("state")), {"progress"})
        self.assertTrue(all(self.mos.mapped("is_locked")))

    def test_yes_prepares_and_starts_in_job_b(self):
        """⑧ „Да“ → задача Б: материализация и старт; бележка, известие."""
        opt = self._cut()
        action = self.mos[:1].action_staged_review_cutting()
        wiz = self.env[action["res_model"]].with_context(**action["context"]).create({})
        self.assertEqual(wiz.production_ids, self.mos, "одобрението е за цялата партида")
        # TG 173315: действието се отваря и от JS (orm.call) — трябват „views“
        self.assertEqual(action["views"], [(False, "form")])
        self.assertEqual(wiz.cutting_optimization_id, opt)
        self.assertEqual(wiz.action_approve_cutting()["tag"], "display_notification")
        self.assertEqual(set(self.mos.mapped("staged_prep_job_state")), {"releasing"})
        self.assertEqual(self._job().method_name, "_staged_release_job")
        with patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            self._perform()
        prepare.assert_called_once_with(start=True)
        self.assertFalse(any(self.mos.mapped("staged_prep_job_state")))

    def test_no_discards_the_cut_and_nothing_stays(self):
        """⑧ „Не“ → разкроят се маха; МО-тата — в Preparation, без разкрой."""
        opt = self._cut()
        action = self.mos.action_staged_review_cutting()
        wiz = self.env[action["res_model"]].with_context(**action["context"]).create({})
        wiz.action_reject_cutting()
        self.assertFalse(opt.exists(), "отказаният разкрой остана")
        self.assertFalse(any(self.mos.mapped("staged_cutting_optimization_id")))
        self.assertFalse(any(self.mos.mapped("staged_prep_job_state")))
        self.assertEqual(set(self.mos.mapped("state")), {"preparation"})
        self.assertIn("rejected", self.mos[0].message_ids[:1].body or "")

    def test_awaiting_blocks_a_new_cut(self):
        """⑧ Докато разкроят чака одобрение — ново ПфП се отказва."""
        self._cut()
        with self.assertRaises(UserError):
            self.mos.action_prepare_production_batch()

    def test_view_cutting_opens_a_new_tab_and_keeps_the_screen(self):
        """Любо 21.10: „Виж разкроя“ не заменя прозореца — нов раздел."""
        self._cut()
        action = self.mos.action_staged_review_cutting()
        wiz = self.env[action["res_model"]].with_context(**action["context"]).create({})
        view = wiz.action_view_cutting()
        if view["type"] == "ir.actions.act_url":
            self.assertEqual(view["target"], "new")
        else:
            self.assertEqual(view["target"], "new")

    def test_cut_warnings_stay_on_the_approval_screen(self):
        """⑨ Предупреждението от разкроя — в екрана „Да/Не“ и в бележката."""
        self._cut()
        self.assertIn("no mrp.saw.format mapping", self.mos[0].staged_prep_warnings or "")
        self.assertIn("no mrp.saw.format mapping", self.mos[0].message_ids[:1].body or "")
        action = self.mos.action_staged_review_cutting()
        wiz = self.env[action["res_model"]].with_context(**action["context"]).create({})
        self.assertEqual(wiz.prep_warnings.count("no mrp.saw.format mapping"), 1,
                         "едно и също предупреждение — веднъж за партидата")

    def test_yes_with_top_up_applies_cuts_again_and_prepares(self):
        """ADR-0099: „Да, с допълването“ → приложи → нов разкрой → подготовка."""
        opt = self._cut()
        line = self.env["mrp.production.topup"].create({
            "optimization_id": opt.id, "product_id": self.mos[0].product_id.id,
            "production_id": self.mos[0].id, "block_qty": 1, "qty": 2, "cut_mm": 100})
        action = self.mos.action_staged_review_cutting()
        wiz = self.env[action["res_model"]].with_context(**action["context"]).create({})
        self.assertEqual(wiz.topup_ids, line)
        wiz.action_approve_with_topup()
        with patch.object(type(self.env["mrp.production"]), "_staged_apply_topups",
                          return_value=self.env["mrp.production"]) as apply_, \
                patch(MODEL + "._staged_optimize_and_gate") as gate, \
                patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            self._perform()
        apply_.assert_called_once()
        gate.assert_called_once()
        prepare.assert_called_once_with(start=True)
        self.assertFalse(line.exists(), "предложението остана след подготовката")

    def test_without_top_up_ignores_the_proposal(self):
        """ADR-0099: „Без допълване“ → разкроят както е, предложението се маха."""
        opt = self._cut()
        line = self.env["mrp.production.topup"].create({
            "optimization_id": opt.id, "product_id": self.mos[0].product_id.id,
            "block_qty": 1, "qty": 2, "cut_mm": 100})
        action = self.mos.action_staged_review_cutting()
        self.env[action["res_model"]].with_context(**action["context"]).create({}).action_approve_cutting()
        with patch.object(type(self.env["mrp.production"]), "_staged_apply_topups") as apply_, \
                patch(MODEL + "._staged_optimize_and_gate") as gate, \
                patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            self._perform()
        apply_.assert_not_called()
        gate.assert_not_called()
        prepare.assert_called_once_with(start=True)
        self.assertFalse(line.exists())

    def test_job_b_warnings_stay_in_the_note(self):
        """TG 173318: предупреждението от задача Б — и в бележката на МО-то."""
        self._cut()
        action = self.mos.action_staged_review_cutting()
        self.env[action["res_model"]].with_context(**action["context"]).create({}).action_approve_cutting()

        def prepare(mos, start=False):
            logging.getLogger("odoo.addons.cutting_t0098").warning("Incomplete machine export T0098")
        with patch(MODEL + "._staged_do_prepare", autospec=True, side_effect=prepare), \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            self._perform()
        self.assertIn("Incomplete machine export T0098", self.mos[0].message_ids[:1].body or "")

    def test_a_replaced_cut_does_not_stay_empty(self):
        """TG 173318: с допълването старият разкрой се заменя — и се маха."""
        old = self._cut()
        self.env["mrp.production.topup"].create({
            "optimization_id": old.id, "product_id": self.mos[0].product_id.id,
            "production_id": self.mos[0].id, "block_qty": 1, "qty": 2, "cut_mm": 100})
        action = self.mos.action_staged_review_cutting()
        self.env[action["res_model"]].with_context(**action["context"]).create({}).action_approve_with_topup()
        new = self.env["mrp.cutting.optimization"].create({
            "name": "T0098 new", "material_domain": "mrp_production"})

        def gate(mos):
            mos.write({"staged_cutting_optimization_id": new.id})
            return new
        with patch.object(type(self.env["mrp.production"]), "_staged_apply_topups",
                          return_value=self.env["mrp.production"]), \
                patch(MODEL + "._staged_optimize_and_gate", autospec=True, side_effect=gate), \
                patch(MODEL + "._staged_do_prepare"), \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            self._perform()
        self.assertFalse(old.exists(), "замененият разкрой остана")
        self.assertTrue(new.exists())
