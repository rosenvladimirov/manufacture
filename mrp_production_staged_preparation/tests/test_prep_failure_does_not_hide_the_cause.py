# -*- coding: utf-8 -*-
"""Обработчикът на провала не бива да пада сам (задача №312).

На 25.11.2026 на RC1, в деня на обучението, 21 МО (M001134, M001155–M001174)
останаха да висят на „Preparation running“, 15 %, етап „Cutting again with
the top-up“. Задачата беше ПАДНАЛА, но МО-тата не бяха отбелязани като
паднали и бутонът им е скрит в това състояние — тоест нямаше как човек да
ги върне от екрана.

Какво се беше случило: `_staged_release_job` работи в savepoint и при
допълване СЪЗДАВА МО (`self |= new`). Гръмна нещо след това, savepoint-ът
се върна, редът изчезна от базата, а recordset-ът още носеше id-то му
(mrp.production(1175)). Обработчикът `_staged_prep_fail` веднага прочете
`", ".join(self.mapped("name"))` и гръмна с MissingError — ВМЕСТО да запише
причината. Така истинската грешка не стигна до никого, а `write` след него
изобщо не се изпълни.

Тук се заковава:
  ① провал след допълване: истинската причина стига до МО-тата, а не
    MissingError от самия обработчик;
  ② нито едно МО не остава в „releasing“ — всички са „failed“;
  ③ обработчикът преживява запис, който вече не съществува, и казва в
    лога кой е изчезнал;
  ④ recordset САМО от изчезнали записи не гърми (и не пише никъде).
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.queue_job.job import Job

MODEL = "odoo.addons.mrp_production_staged_preparation.models.mrp_production.MrpProduction"
LOGGER = "odoo.addons.mrp_production_staged_preparation.models.mrp_production"

# Дословно причината, която трябва да стигне до човека. Ако обработчикът
# падне, на нейно място излиза MissingError и тестът го вижда.
REAL_CAUSE = "Saw 'T0098' has no mrp.saw.format mapping"


@tagged("post_install", "-at_install")
class TestPrepFailureDoesNotHideTheCause(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        product = cls.env["product.product"].create({
            "name": "T0312 window", "is_storable": True})
        cls.product = product
        cls.mos = cls.env["mrp.production"].create([
            {"product_id": product.id, "product_qty": 1.0} for _i in range(2)])
        cls.mos.picking_type_id.staged_preparation_enabled = True
        cls.mos.write({"state": "preparation"})

    # ─── помощни ───────────────────────────────────────────────

    def _cut_and_approve_with_topup(self):
        """Довежда партидата до „Да, с допълването“ — както на RC1."""
        self.mos.action_prepare_production_batch()
        opt = self.env["mrp.cutting.optimization"].create({
            "name": "T0312 cut", "material_domain": "mrp_production"})

        def gate(mos):
            mos.write({"staged_cutting_optimization_id": opt.id})
            return opt
        with patch(MODEL + "._staged_optimize_and_gate", autospec=True,
                   side_effect=gate), \
                patch(MODEL + "._staged_do_prepare"), \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            Job.load(self.env, self.mos[:1].staged_prep_job_uuid).perform()
        line = self.env["mrp.production.topup"].create({
            "optimization_id": opt.id, "product_id": self.product.id,
            "production_id": self.mos[0].id, "block_qty": 1, "qty": 2,
            "cut_mm": 100})
        action = self.mos.action_staged_review_cutting()
        wiz = self.env[action["res_model"]].with_context(
            **action["context"]).create({})
        # Проверките са нарочни: ако нещо оттук не е наред, тестът трябва да
        # каже КОЕ, вместо да гръмне по-късно с IndexError на празен списък.
        self.assertEqual(wiz.topup_ids, line,
                         "визардът не вижда предложението за допълване")
        wiz.action_approve_with_topup()
        job = self.env["queue.job"].search(
            [("uuid", "=", self.mos[:1].staged_prep_job_uuid)])
        self.assertEqual(job.method_name, "_staged_release_job",
                         "одобрението не пусна задача Б")
        self.assertTrue(job.kwargs.get("topup"),
                        "задача Б е пусната БЕЗ допълване")
        return opt

    def _perform_failing_topup(self):
        """Задача Б: допълването ражда МО, следващата стъпка гърми.

        Точно подредбата от RC1 — новото МО е създадено ВЪТРЕ в savepoint-а
        и не преживява отката, но `self` вече го носи.
        """
        # Трите условия, от които зависи дали задача Б изобщо стига до
        # допълването: `todo` (състояние + released), закаченият разкрой и
        # самото предложение. Проверяват се ПОИМЕННО, за да се вижда кое.
        self.assertEqual(set(self.mos.mapped("state")), {"preparation"},
                         "МО-тата не са в Preparation — `todo` ще е празно")
        self.assertFalse(any(self.mos.mapped("staged_released")),
                         "вече са пуснати към цеха — `todo` ще е празно")
        self.assertTrue(all(self.mos.mapped("staged_cutting_optimization_id")),
                        "няма закачен разкрой — `opts` ще е празно")
        self.assertTrue(
            self.env["mrp.production.topup"].search_count([]),
            "предложението за допълване е изчезнало преди задача Б")
        born = []

        def apply_topups(mos, lines):
            # Както в setUpClass: `state` се пише отделно — при create
            # то е computed и подаването му там гърми, а изключението се
            # губи в `except Exception` на задачата.
            new = self.env["mrp.production"].create({
                "product_id": self.product.id, "product_qty": 2.0})
            new.write({"state": "preparation"})
            born.append(new)
            return new

        with patch.object(type(self.env["mrp.production"]),
                          "_staged_apply_topups", autospec=True,
                          side_effect=apply_topups), \
                patch(MODEL + "._staged_optimize_and_gate", autospec=True,
                      side_effect=ValueError(REAL_CAUSE)), \
                patch(MODEL + "._staged_do_prepare") as prepare, \
                patch.object(type(self.env["bus.bus"]), "_sendone"):
            Job.load(self.env, self.mos[:1].staged_prep_job_uuid).perform()
        prepare.assert_not_called()
        return born[0]

    # ─── ① причината стига до човека ────────────────────────────

    def test_the_real_cause_reaches_the_orders_not_a_missing_error(self):
        self._cut_and_approve_with_topup()
        self._perform_failing_topup()
        for mo in self.mos:
            self.assertEqual(mo.staged_prep_error, REAL_CAUSE)
            self.assertNotIn("does not exist", mo.staged_prep_error or "")

    def test_the_cause_is_in_the_chatter_too(self):
        self._cut_and_approve_with_topup()
        self._perform_failing_topup()
        body = self.mos[0].message_ids[:1].body or ""
        self.assertIn(REAL_CAUSE, body)

    # ─── ② нищо не остава да виси ───────────────────────────────

    def test_no_order_is_left_in_releasing(self):
        """Това държеше 21-те МО на RC1 — без бутон, по който да се върнат."""
        self._cut_and_approve_with_topup()
        self._perform_failing_topup()
        self.assertEqual(set(self.mos.mapped("staged_prep_job_state")),
                         {"failed"})

    def test_the_born_order_is_gone_with_the_savepoint(self):
        """Описанието на случая: МО-то наистина не преживява отката."""
        self._cut_and_approve_with_topup()
        born = self._perform_failing_topup()
        self.assertFalse(born.exists())

    # ─── ③ и ④ самият обработчик ────────────────────────────────

    def test_the_handler_survives_a_record_that_is_gone(self):
        ghost = self.env["mrp.production"].create({
            "product_id": self.product.id, "product_qty": 1.0})
        ghost_id = ghost.id
        ghost.unlink()
        mixed = self.mos | self.env["mrp.production"].browse(ghost_id)
        with patch.object(type(self.env["bus.bus"]), "_sendone"), \
                self.assertLogs(LOGGER, level="WARNING") as logs:
            result = mixed._staged_prep_fail(ValueError(REAL_CAUSE), "подготовката")
        self.assertFalse(result)
        self.assertEqual(set(self.mos.mapped("staged_prep_job_state")),
                         {"failed"})
        self.assertTrue(
            any(str(ghost_id) in line for line in logs.output),
            "логът не каза кой запис е изчезнал")

    # ─── ⑤ заклещеното състояние: бутонът пита живота, не полето ──

    def test_a_dead_job_no_longer_holds_the_button(self):
        """Причината, поради която 21-те МО трябваше да се пипат на ръка.

        Сървърът (`_staged_prep_check_not_running`) отдавна пита опашката,
        а изгледът питаше полето — и криеше бутона на МО, чиято задача е
        умряла. Сега двете казват едно и също.
        """
        self.mos.action_prepare_production_batch()
        self.mos.write({"staged_prep_job_state": "releasing"})
        job = self.env["queue.job"].search(
            [("uuid", "=", self.mos[:1].staged_prep_job_uuid)])
        job.state = "failed"
        self.mos.invalidate_recordset(["staged_prep_job_alive"])
        self.assertFalse(any(self.mos.mapped("staged_prep_job_alive")))
        self.assertFalse(self.mos._staged_prep_running(),
                         "сървърът и екранът трябва да казват едно и също")

    def test_a_live_job_still_holds_the_button(self):
        self.mos.action_prepare_production_batch()
        self.assertTrue(all(self.mos.mapped("staged_prep_job_alive")))

    def test_an_order_that_never_ran_is_not_alive(self):
        self.assertFalse(any(self.mos.mapped("staged_prep_job_alive")))

    def test_a_recordset_of_only_gone_records_writes_nothing(self):
        ghost = self.env["mrp.production"].create({
            "product_id": self.product.id, "product_qty": 1.0})
        ghost_id = ghost.id
        ghost.unlink()
        gone = self.env["mrp.production"].browse(ghost_id)
        with patch.object(type(self.env["bus.bus"]), "_sendone") as sendone:
            self.assertFalse(
                gone._staged_prep_fail(ValueError(REAL_CAUSE), "подготовката"))
        sendone.assert_not_called()
