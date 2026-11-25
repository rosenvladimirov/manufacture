# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import datetime, timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.api import call_kw
from odoo.tests import new_test_user, tagged

from .common import MONDAY, CrewWorkorderCommon

FRIDAY = MONDAY - timedelta(days=3)
SUNDAY = MONDAY - timedelta(days=1)
TUESDAY = MONDAY + timedelta(days=1)
WEDNESDAY = MONDAY + timedelta(days=2)
# 05.10.2026 11:00 в София (UTC+3) — „сега“ във всички тестове.
FROZEN_NOW = "2026-10-05 08:00:00"


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReplanEngine(CrewWorkorderCommon):
    """Тест 6 от TECH_DESIGN §6: двигателят на препланирането (M6) и
    партидата със снимката. Календарът е този на Полигруп (И1, Р28):
    08–12, обяд 12–13, 13–17 всеки ден; „сега“ е понеделник 11:00."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Batch = cls.env["mrp.workcenter.replan.batch"]
        cls.crew12 = cls.emp1 | cls.emp2
        cls.wc_alt = cls._make_workcenter("WC Alternative", cls.cal_pg)

    # --- помощни ---------------------------------------------------------

    def _mo(self, deadline=None, priority="0"):
        mo = self.env["mrp.production"].create(
            {
                "product_id": self.product.id,
                "product_qty": 1.0,
                "priority": priority,
                "date_deadline": deadline,
            }
        )
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed")
        return mo

    def _stale(self, minutes=60.0, mo=None, workcenter=None, **extra):
        """Незапочната поръчка, планирана в миналото (петък 09:00)."""
        return self._make_wo(
            workcenter or self.wc_pg,
            self._utc(FRIDAY, 9),
            minutes=minutes,
            mo=mo or self._mo(),
            overlap=True,
            **extra,
        )

    def _run(self, **params):
        values = {
            "workcenter_ids": [self.wc_pg.id],
            "date_from": MONDAY,
            "date_to": MONDAY + timedelta(days=14),
        }
        values.update(params)
        return self.Batch._crew_run(values, "wizard")

    def _line(self, batch, wo):
        return batch.line_ids.filtered(lambda line: line.workorder_id == wo)

    def _time_line(self, wo, start, end):
        loss = self.env["mrp.workcenter.productivity.loss"].search(
            [("loss_type", "=", "productive")], limit=1
        )
        return self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": wo.id,
                "workcenter_id": wo.workcenter_id.id,
                "loss_id": loss.id,
                "employee_id": self.emp3.id,
                "date_start": start,
                "date_end": end,
            }
        )

    def assertSlot(self, wo, day, hour, end_day, end_hour, msg=None):
        self.assertEqual(
            (wo.date_start, wo.date_finished),
            (self._utc(day, hour), self._utc(end_day, end_hour)),
            msg,
        )

    # --- M6.3: незапочнатите, от „сега“ ------------------------------------

    def test_stale_moved_from_now(self):
        """Незапочната поръчка в миналото → от днес; нищо преди „сега“."""
        wo = self._stale()
        batch = self._run()
        self.assertSlot(wo, MONDAY, 11, MONDAY, 12)
        self.assertGreaterEqual(wo.date_start, datetime(2026, 10, 5, 8, 0))
        self.assertEqual(self._line(batch, wo).result, "moved")
        self.assertEqual(batch.source, "wizard")
        self.assertEqual(batch.state, "applied")

    def test_time_ids_not_moved(self):
        """Поръчка с отчетено време не е кандидат — планът ѝ не се пипа."""
        wo = self._stale()
        self._time_line(wo, self._utc(FRIDAY, 9), self._utc(FRIDAY, 9, 30))
        leave = wo.leave_id
        batch = self._run()
        self.assertFalse(self._line(batch, wo))
        self.assertEqual(wo.leave_id, leave)
        self.assertSlot(wo, FRIDAY, 9, FRIDAY, 10)

    def test_successor_in_progress_not_moved(self):
        """Поръчка, чийто наследник е в progress, не се мести."""
        mo = self._mo()
        pred = self._stale(mo=mo, sequence=1)
        succ = self._make_wo(
            self.wc_pg, self._utc(FRIDAY, 10), minutes=60, mo=mo, sequence=2
        )
        self.assertEqual(succ.blocked_by_workorder_ids, pred)
        succ.state = "progress"
        batch = self._run()
        self.assertFalse(self._line(batch, pred))
        self.assertSlot(pred, FRIDAY, 9, FRIDAY, 10)

    def test_successor_on_other_center_is_pushed_after(self):
        """18.0.1.12.0 (Росен 08.11, вариант „б“): „Rearrange Plan“ на център
        избутва наследника на ДРУГ център след препланирания предшественик —
        монтажът след цеха (M002089); с отстъпа `_crew_dependency_gap`."""
        mo = self._mo()
        pred = self._stale(mo=mo, sequence=1)
        succ = self._make_wo(
            self.wc_2x12, self._utc(FRIDAY, 10), minutes=60, mo=mo, sequence=2, overlap=True
        )
        self.assertEqual(succ.blocked_by_workorder_ids, pred)
        old_succ = (succ.date_start, succ.date_finished)
        batch = self._run()
        self.assertGreater(pred.date_start, self._utc(FRIDAY, 10), "предшественикът е препланиран")
        self.assertGreaterEqual(succ.date_start, pred.date_finished, "наследникът — след него")
        # Клаудио (№199): „Undo“ на пренареждането връща и избутания наследник
        self.assertIn(succ, batch.line_ids.workorder_id)
        batch.action_undo()
        self.assertEqual((succ.date_start, succ.date_finished), old_succ)
        # отстъпът (Теолино: монтажът поне 24 ч след цеха) — точка за разширение
        WorkOrder = type(self.env["mrp.workorder"])
        gap = timedelta(hours=24)
        with patch.object(WorkOrder, "_crew_dependency_gap", lambda self, predecessor: gap):
            mo2 = self._mo()
            pred2 = self._stale(mo=mo2, sequence=1)
            succ2 = self._make_wo(
                self.wc_2x12, self._utc(FRIDAY, 11), minutes=60, mo=mo2, sequence=2, overlap=True
            )
            self._run()
            self.assertGreaterEqual(succ2.date_start, pred2.date_finished + gap)

    def test_progress_with_expired_end_blocks_slot(self):
        """Поръчка в progress с изтекъл край (09–10) заема [сега, сега +
        остатък] = 11–12 → кандидатът отива след обяда."""
        running = self._make_wo(self.wc_pg, self._utc(MONDAY, 9), minutes=60)
        running.state = "progress"
        wo = self._stale(minutes=30)
        self._run()
        self.assertEqual(
            (wo.date_start, wo.date_finished),
            (self._utc(MONDAY, 13), self._utc(MONDAY, 13, 30)),
        )
        self.assertSlot(running, MONDAY, 9, MONDAY, 10, "започнатата не се мести")

    def test_only_selected_workcenters(self):
        other = self._stale(workcenter=self.wc_2x12)
        leave = other.leave_id
        self._run()
        self.assertEqual(other.leave_id, leave)

    def test_scope_late(self):
        """`scope='late'` взима само закъснелите."""
        late = self._stale(mo=self._mo(deadline=self._utc(SUNDAY, 12)))
        on_time = self._stale(mo=self._mo(deadline=self._utc(WEDNESDAY, 12)))
        self.assertTrue(late.is_late)
        self.assertFalse(on_time.is_late)
        batch = self._run(scope="late")
        self.assertEqual(batch.line_ids.workorder_id, late)
        self.assertSlot(on_time, FRIDAY, 9, FRIDAY, 10)

    # --- M6.4: ред --------------------------------------------------------

    def test_order_by_deadline(self):
        """Срокът на МО: по-ранният напред, без срок — накрая."""
        wo_a = self._stale(mo=self._mo(deadline=self._utc(WEDNESDAY, 12)))
        wo_c = self._stale(mo=self._mo())
        wo_b = self._stale(mo=self._mo(deadline=self._utc(TUESDAY, 12)))
        batch = self._run()
        self.assertSlot(wo_b, MONDAY, 11, MONDAY, 12)
        self.assertSlot(wo_a, MONDAY, 13, MONDAY, 14)
        self.assertSlot(wo_c, MONDAY, 14, MONDAY, 15)
        self.assertEqual(
            batch.line_ids.sorted("sequence").workorder_id.ids,
            [wo_b.id, wo_a.id, wo_c.id],
        )

    def test_order_by_mo_priority(self):
        low = self._stale(mo=self._mo(priority="0"))
        high = self._stale(mo=self._mo(priority="1"))
        self._run(priority_key="mo_priority")
        self.assertSlot(high, MONDAY, 11, MONDAY, 12)
        self.assertSlot(low, MONDAY, 13, MONDAY, 14)

    def test_priority_breaks_deadline_tie(self):
        """При еднакъв срок по-високият приоритет на МО е напред."""
        deadline = self._utc(TUESDAY, 12)
        low = self._stale(mo=self._mo(deadline=deadline, priority="0"))
        high = self._stale(mo=self._mo(deadline=deadline, priority="1"))
        self._run()
        self.assertSlot(high, MONDAY, 11, MONDAY, 12)
        self.assertSlot(low, MONDAY, 13, MONDAY, 14)

    def test_order_by_partner(self):
        """Подредба по клиент: по реда на `partner_ids`, без клиент накрая."""
        Partner = self.env["res.partner"]
        p1 = Partner.create({"name": "Crew Customer 1"})
        p2 = Partner.create({"name": "Crew Customer 2"})
        none = self._stale()
        w1 = self._stale()
        w2 = self._stale()
        partners = {w1.id: p1, w2.id: p2}
        WorkOrder = type(self.env["mrp.workorder"])
        with patch.object(
            WorkOrder, "_crew_partner", lambda wo: partners.get(wo.id, Partner)
        ):
            self._run(priority_key="partner", partner_ids=[p2.id, p1.id])
            self.assertSlot(w2, MONDAY, 11, MONDAY, 12)
            self.assertSlot(w1, MONDAY, 13, MONDAY, 14)
            self.assertSlot(none, MONDAY, 14, MONDAY, 15)
            # Филтър по клиент: само неговите поръчки.
            batch = self._run(partner_filter_ids=[p1.id])
            self.assertEqual(batch.line_ids.workorder_id, w1)

    def test_kahn_predecessor_first(self):
        """Наследникът е с по-малко id (ключът го слага напред), но Kahn
        планира предшественика първо, а наследника — след края му."""
        mo = self._mo()
        succ = self._stale(mo=mo, sequence=2)
        pred = self._make_wo(
            self.wc_pg, self._utc(FRIDAY, 10), minutes=60, mo=mo, sequence=1
        )
        self.assertEqual(succ.blocked_by_workorder_ids, pred)
        self.assertLess(succ.id, pred.id)
        batch = self._run()
        self.assertSlot(pred, MONDAY, 11, MONDAY, 12)
        self.assertSlot(succ, MONDAY, 13, MONDAY, 14)
        self.assertEqual(
            batch.line_ids.sorted("sequence").workorder_id.ids, [pred.id, succ.id]
        )

    # --- Р25: затворени смени ----------------------------------------------

    def test_r25_center_without_rosters_is_open(self):
        """Център без нито един наряд в периода: смените са отворени дори
        при `respect_roster=True`."""
        wo = self._stale()
        self._run(respect_roster=True)
        self.assertSlot(wo, MONDAY, 11, MONDAY, 12)

    def test_r25_shift_without_roster_is_closed(self):
        """Има наряд в периода (вторник) → понеделник без наряд е затворен
        при `respect_roster=True`; без уважаване — отворен."""
        self._roster(self.wc_pg, TUESDAY, "08:00", self.crew12)
        wo = self._stale()
        self._run(respect_roster=True)
        self.assertSlot(wo, TUESDAY, 8, TUESDAY, 9)
        self.assertEqual(set(wo.employee_assigned_ids.ids), set(self.crew12.ids))
        self._run(respect_roster=False)
        self.assertSlot(wo, MONDAY, 11, MONDAY, 12)

    # --- only_stale ------------------------------------------------------

    def test_only_stale(self):
        """`only_stale` пипа само остарелите/непланираните; бъдещата
        поръчка остава на мястото си."""
        stale = self._stale()
        future = self._make_wo(
            self.wc_pg, self._utc(TUESDAY, 9), minutes=60, mo=self._mo()
        )
        leave = future.leave_id
        batch = self._run(only_stale=True)
        self.assertEqual(batch.line_ids.workorder_id, stale)
        self.assertEqual(future.leave_id, leave)
        self.assertSlot(future, TUESDAY, 9, TUESDAY, 10)
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)

    # --- Ф4: грешка в една поръчка -----------------------------------------

    def test_failed_workorder_rolled_back(self):
        """ValidationError при записа на една поръчка: savepoint-ът я връща,
        тя е `failed` и НЕпланирана; другите са планирани."""
        wo1 = self._stale()
        wo2 = self._stale()
        wo3 = self._stale()
        WorkOrder = type(self.env["mrp.workorder"])
        original = WorkOrder.write

        def write(records, vals):
            res = original(records, vals)
            if (
                "leave_id" in vals
                and wo2.id in records.ids
                and records.env.context.get("crew_engine")
            ):
                raise ValidationError("Extrusion must end before packaging")
            return res

        with patch.object(WorkOrder, "write", write):
            batch = self._run()
        line2 = self._line(batch, wo2)
        self.assertEqual(line2.result, "failed")
        self.assertIn("Extrusion", line2.message)
        self.assertFalse(wo2.leave_id)
        self.assertFalse(wo2.date_start)
        self.assertFalse(
            self.env["resource.calendar.leaves"].search(
                [("name", "=", wo2.display_name)]
            )
        )
        self.assertSlot(wo1, MONDAY, 11, MONDAY, 12)
        self.assertSlot(wo3, MONDAY, 13, MONDAY, 14)
        self.assertEqual(batch.state, "applied")
        self.assertIn("could not be planned", batch.report_html)

    # --- 18.0.1.12.4: предшественикът дава начало само когато е основа ----

    def test_unplanned_predecessor_blocks_planning(self):
        """Предшественик БЕЗ дата ⇒ поръчката НЕ се нарежда, а е `failed`.

        Любо, 16.11 (fulltest M001911, M002236, M002430…): монтажът лягаше,
        докато цехът е `waiting` без дата — тя падаше от сметката вместо да
        спре планирането. Предшественикът е в център ИЗВЪН избраните, за да
        не бъде пренареден и той."""
        mo = self._keep_mo_open(self._mo())
        pred = self._make_wo(self.wc_alt, self._utc(FRIDAY, 9), mo=mo, sequence=1)
        succ = self._stale(mo=mo, sequence=2)
        self.assertEqual(succ.blocked_by_workorder_ids, pred)
        pred.leave_id.unlink()
        pred.write({"date_start": False, "date_finished": False})
        batch = self._run()
        line = self._line(batch, succ)
        self.assertEqual(line.result, "failed")
        self.assertIn("not planned", line.message)
        self.assertFalse(succ.date_start, "остава непланирана, не лягва пред цеха")
        self.assertIn("could not be planned", batch.report_html)

    def test_late_unfinished_predecessor_blocks_planning(self):
        """Незавършен предшественик с МИНАЛА дата също не е основа.

        Любо, 16.11 (M001912): Production PVC е `waiting` с дата 30.09, а
        монтажът отскачаше към „сега“, сякаш цехът е готов. 125 закъснели
        операции минаха така."""
        mo = self._keep_mo_open(self._mo())
        pred = self._make_wo(self.wc_alt, self._utc(FRIDAY, 9), mo=mo, sequence=1)
        succ = self._stale(mo=mo, sequence=2)
        self.assertEqual(succ.blocked_by_workorder_ids, pred)
        self.assertNotEqual(pred.state, "done")
        self.assertLess(pred.date_finished, datetime(2026, 10, 5, 8, 0))
        batch = self._run()
        line = self._line(batch, succ)
        self.assertEqual(line.result, "failed")
        self.assertIn(pred.display_name, line.message)
        self.assertFalse(succ.date_start)

    def test_done_predecessor_in_the_past_still_plans(self):
        """ПРИКЛЮЧЕН предшественик с минала дата е факт ⇒ наследникът се
        нарежда нормално, от „сега“. Регресията, която новата проверка не
        бива да закача."""
        mo = self._keep_mo_open(self._mo())
        pred = self._make_wo(self.wc_alt, self._utc(FRIDAY, 9), mo=mo, sequence=1)
        succ = self._stale(mo=mo, sequence=2)
        self.assertEqual(succ.blocked_by_workorder_ids, pred)
        pred.state = "done"
        batch = self._run()
        self.assertEqual(self._line(batch, succ).result, "moved")
        self.assertSlot(succ, MONDAY, 11, MONDAY, 12)

    def test_dependency_gap_applies_on_replan(self):
        """Отстъпът по `_crew_dependency_gap` важи и при пренареждането.

        Любо, 16.11 (M002090/91/92): L Frame почваше точно в края на
        Production ALU. Отстъпът се прилагаше само за наследници ИЗВЪН
        избраните центрове (`_crew_push_foreign_successors`), а монтажът при
        „Rearrange“ е сред избраните."""
        mo = self._keep_mo_open(self._mo())
        pred = self._make_wo(self.wc_alt, self._utc(MONDAY, 13), mo=mo, sequence=1)
        succ = self._stale(mo=mo, sequence=2)
        self.assertEqual(succ.blocked_by_workorder_ids, pred)
        self.assertEqual(pred.date_finished, self._utc(MONDAY, 14))
        WorkOrder = type(self.env["mrp.workorder"])
        with patch.object(
            WorkOrder, "_crew_dependency_gap", lambda self, predecessor: timedelta(hours=24)
        ):
            batch = self._run()
        self.assertEqual(self._line(batch, succ).result, "moved")
        self.assertSlot(succ, TUESDAY, 14, TUESDAY, 15)

    def test_outside_period(self):
        """Краят е след `date_to` → `outside_period`, но поръчката е планирана."""
        wo = self._stale(minutes=600)
        batch = self._run(date_to=MONDAY)
        self.assertEqual(self._line(batch, wo).result, "outside_period")
        self.assertTrue(wo.leave_id)
        self.assertEqual(wo.date_start, self._utc(MONDAY, 11))
        self.assertGreater(wo.date_finished, self._utc(TUESDAY, 0))

    # --- M6.8: МО ---------------------------------------------------------

    def test_mo_dates_force_date(self):
        """Датите на МО = min/max на планираните поръчки; МО не е unplan-ната."""
        mo = self._mo()
        first = self._stale(mo=mo, sequence=1)
        second = self._make_wo(
            self.wc_pg, self._utc(FRIDAY, 10), minutes=60, mo=mo, sequence=2
        )
        self._run()
        self.assertTrue(first.leave_id and second.leave_id)
        self.assertTrue(mo.is_planned)
        self.assertEqual(mo.date_start, self._utc(MONDAY, 11))
        self.assertEqual(mo.date_finished, self._utc(MONDAY, 14))

    # --- M6.5: снимката -----------------------------------------------------

    def test_snapshot_complete(self):
        """Снимката пази стария и новия план на всяка поръчка и датите на
        МО; старият leave е изтрит (т. 6)."""
        mo = self._mo(deadline=self._utc(TUESDAY, 12))
        wo = self._stale(mo=mo)
        old = (wo.workcenter_id, wo.date_start, wo.date_finished, wo.duration_expected)
        old_mo = (mo.date_start, mo.date_finished)
        old_leave = wo.leave_id
        batch = self._run()
        line = self._line(batch, wo)
        self.assertEqual(
            (
                line.old_workcenter_id,
                line.old_date_start,
                line.old_date_finished,
                line.old_duration_expected,
            ),
            old,
        )
        self.assertEqual(
            (
                line.new_workcenter_id,
                line.new_date_start,
                line.new_date_finished,
                line.new_duration_expected,
            ),
            (wo.workcenter_id, wo.date_start, wo.date_finished, wo.duration_expected),
        )
        self.assertEqual(line.production_id, mo)
        self.assertEqual(line.result, "moved")
        self.assertFalse(old_leave.exists())
        snapshot = batch.production_snapshot[str(mo.id)]
        self.assertEqual(
            (snapshot["date_start"], snapshot["date_finished"]),
            tuple(v.strftime("%Y-%m-%d %H:%M:%S") for v in old_mo),
        )
        self.assertEqual(batch.params["date_from"], "2026-10-05")
        self.assertEqual(batch.workcenter_ids, self.wc_pg)
        self.assertIn(wo.display_name, batch.report_html)

    # --- алтернативи --------------------------------------------------------

    def test_use_alternatives(self):
        """Центърът е зает до края на деня (поръчка с отчетено време):
        без алтернативи — вторник; с алтернативи в обхвата — другият център."""
        self.wc_pg.alternative_workcenter_ids = self.wc_alt
        busy = self._make_wo(self.wc_pg, self._utc(MONDAY, 11), minutes=360)
        self._time_line(busy, self._utc(MONDAY, 7), self._utc(MONDAY, 7, 5))
        wo = self._stale()
        scope = [self.wc_pg.id, self.wc_alt.id]
        self._run(workcenter_ids=scope)
        self.assertEqual(wo.workcenter_id, self.wc_pg)
        self.assertSlot(wo, TUESDAY, 8, TUESDAY, 9)
        self._run(workcenter_ids=scope, use_alternatives=True)
        self.assertEqual(wo.workcenter_id, self.wc_alt)
        self.assertSlot(wo, MONDAY, 11, MONDAY, 12)

    def test_use_alternatives_from_gantt_context(self):
        """M10 (Ф3): пуснат от Ганта „Планирай център“ (контекстът на
        действието носи `crew_workcenter_id`), двигателят пак мести в
        алтернативния център — гардът е само на флага на влаченето."""
        self.wc_pg.alternative_workcenter_ids = self.wc_alt
        busy = self._make_wo(self.wc_pg, self._utc(MONDAY, 11), minutes=360)
        self._time_line(busy, self._utc(MONDAY, 7), self._utc(MONDAY, 7, 5))
        wo = self._stale()
        batch = self.Batch.with_context(crew_workcenter_id=self.wc_pg.id)._crew_run(
            {
                "workcenter_ids": [self.wc_pg.id, self.wc_alt.id],
                "date_from": MONDAY,
                "date_to": MONDAY + timedelta(days=14),
                "use_alternatives": True,
            },
            "recompute",
        )
        self.assertEqual(self._line(batch, wo).result, "moved")
        self.assertEqual(wo.workcenter_id, self.wc_alt)
        self.assertSlot(wo, MONDAY, 11, MONDAY, 12)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestRecompute(CrewWorkorderCommon):
    """Тест 8 от TECH_DESIGN §6: „Преизчисли“ (M7, SPEC §6.4, Р25)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.crew12 = cls.emp1 | cls.emp2
        cls.mrp_user = new_test_user(
            cls.env,
            login="crew_recompute_user",
            email="crew_recompute_user@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )

    def _mo(self):
        mo = self.env["mrp.production"].create(
            {"product_id": self.product.id, "product_qty": 1.0}
        )
        mo.action_confirm()
        return mo

    def _stale(self):
        return self._make_wo(self.wc_pg, self._utc(FRIDAY, 9), mo=self._mo())

    def _done_with_time(self):
        """Приключена днес поръчка с 2 часа на emp3 — без наряд (не е
        делена при приключването). МО-то остава отворено (гардът M5.9 е
        отделна проверка — `guarded`)."""
        wo = self._make_wo(
            self.wc_pg,
            self._utc(MONDAY, 8),
            minutes=120,
            mo=self._keep_mo_open(self._mo()),
        )
        loss = self.env["mrp.workcenter.productivity.loss"].search(
            [("loss_type", "=", "productive")], limit=1
        )
        self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": wo.id,
                "workcenter_id": self.wc_pg.id,
                "loss_id": loss.id,
                "employee_id": self.emp3.id,
                "date_start": self._utc(MONDAY, 8),
                "date_end": self._utc(MONDAY, 10),
            }
        )
        wo.button_finish()
        self.assertEqual(wo.state, "done")
        self.assertNotEqual(wo.production_id.state, "done")
        self.assertEqual(wo.time_ids.employee_id, self.emp3)
        return wo

    def test_recompute_respect_roster_off_by_default(self):
        """Р25: в „Преизчисли“ смените без наряд НЕ са затворени по
        подразбиране; партидата е `recompute` с only_stale и без алтернативи."""
        self._roster(self.wc_pg, TUESDAY, "08:00", self.crew12)
        wo = self._stale()
        batch = self.wc_pg._crew_recompute()
        self.assertEqual(wo.date_start, self._utc(MONDAY, 11))
        self.assertEqual(batch.source, "recompute")
        self.assertEqual(
            (
                batch.params["respect_roster"],
                batch.params["only_stale"],
                batch.params["use_alternatives"],
                batch.params["date_from"],
            ),
            (False, True, False, "2026-10-05"),
        )

    def test_recompute_applies_crew_and_splits_day(self):
        """M7: препланира, прилага наряда, дели приключените за деня;
        гардът M5.9 пропуска приключената МО."""
        done = self._done_with_time()
        guarded = self._done_with_time()
        guarded.production_id.state = "done"
        stale = self._stale()
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        batch = self.wc_pg._crew_recompute(MONDAY)
        self.assertEqual(stale.date_start, self._utc(MONDAY, 11))
        self.assertEqual(set(stale.employee_assigned_ids.ids), set(self.crew12.ids))
        self.assertEqual(
            set(done.time_ids.employee_id.ids), set(self.crew12.ids), "делено"
        )
        self.assertEqual(guarded.time_ids.employee_id, self.emp3, "гардът M5.9")
        self.assertIn("Split among the crew", batch.report_html)
        self.assertIn("the manufacturing order is done", batch.report_html)

    def test_recompute_buttons(self):
        """Бутоните в наряда: центърът от контекста (списъкът) или от
        наряда (формата); MRP User може (Р24)."""
        roster = self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._stale()
        Roster = self.env["mrp.workcenter.roster"].with_user(self.mrp_user)
        with self.assertRaises(UserError):
            Roster.action_crew_recompute()
        action = Roster.with_context(
            crew_workcenter_id=self.wc_pg.id
        ).action_crew_recompute()
        self.assertEqual(action["res_model"], "mrp.workcenter.replan.batch")
        batch = self.env["mrp.workcenter.replan.batch"].browse(action["res_id"])
        self.assertEqual(batch.user_id, self.mrp_user)
        self.assertEqual(batch.line_ids.workorder_id, wo)
        action = roster.with_user(self.mrp_user).action_crew_recompute_roster()
        self.assertEqual(action["res_model"], "mrp.workcenter.replan.batch")


    def test_recompute_button_via_call_kw(self):
        """19.0.1.6.1 (дефект от живия тест 09.10): „Recompute“ в хедъра на
        списъка минава през `call_button` → `call_kw` с ids като първи
        аргумент — празни и избрани; Гантът вика същото с `[[]]`."""
        roster = self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        wo = self._stale()
        Roster = self.env["mrp.workcenter.roster"].with_user(self.mrp_user)
        context = {"crew_workcenter_id": self.wc_pg.id}
        batches = self.env["mrp.workcenter.replan.batch"]
        for ids in ([], roster.ids):
            action = call_kw(Roster, "action_crew_recompute", [ids], {"context": context})
            self.assertEqual(action["res_model"], "mrp.workcenter.replan.batch")
            batches |= batches.browse(action["res_id"])
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches.user_id, self.mrp_user)
        # Първият пуск мести остарялата поръчка; вторият няма какво.
        self.assertEqual(batches[0].line_ids.workorder_id, wo)
