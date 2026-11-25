# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Стъпка 6в (19.0.1.5.1): тестовете на петте находки от втората двойка
обратни проверки на пистите (07.10.2026). Всеки тест падаше на кода при
19.0.1.5.0 (8729f0e) и пази правилото, което находката сочи:

1. Р30 — свободен leave `other` удря печата на засегнатите центрове, затова
   едновременен запис на поръчка в същия център не минава покрай него
   (write skew). Тук е структурната част; истинските две транзакции са в
   пробата testlogs/s6c_probe_skew.py.
2. Р36 / Р37 — грешка от едновременен запис (serialization, deadlock) в
   един център не спира влака за следващите; центърът се опитва още веднъж;
   прогресът на cron-а казва колко остава.
3. Р30 / Р35 — ходът по календара през полунощ (hour_to = 24) не оставя
   микросекунда в края: допирането не е застъпване.
4. Р32 — M17: началото, изтеглено до „сега“ или до края на предшественика,
   пак се изкарва извън вагоните (не влиза в започнатата, не пренарежда).
5. Р37 — стартът през ръчно отчетено време (`_set_duration`) е старт:
   планираният край се пази и тревогата върви.
"""
from unittest.mock import patch

from freezegun import freeze_time
from psycopg2 import errors

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import SQL

from .common import MONDAY
from .test_lanes import FROZEN_NOW, TUESDAY, WEDNESDAY, CrewLanesCommon


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReview2FreeLeaveStamp(CrewLanesCommon):
    """Находка 1 (Р30): leave `other` без поръчка удря печата на центровете,
    които засяга — ресурсът на центъра или (глобален leave) календарът."""

    def _stamps(self):
        workcenters = self.wc_pg | self.wc_two | self.wc_other | self.wc_2x12
        self.env.cr.execute(
            SQL(
                "SELECT id, COALESCE(crew_lane_stamp, 0) FROM mrp_workcenter "
                "WHERE id = ANY(%s)",
                workcenters.ids,
            )
        )
        return dict(self.env.cr.fetchall())

    def _leave(self, workcenter=None, calendar=None, day=TUESDAY):
        return self.env["resource.calendar.leaves"].create(
            {
                "name": "Maintenance",
                "resource_id": workcenter.resource_id.id if workcenter else False,
                "calendar_id": calendar.id if calendar else False,
                "date_from": self._utc(day, 9),
                "date_to": self._utc(day, 11),
                "time_type": "other",
            }
        )

    def test_r30_free_leave_stamps_its_center(self):
        before = self._stamps()
        leave = self._leave(self.wc_pg, self.cal_pg)
        after = self._stamps()
        self.assertEqual(after[self.wc_pg.id], before[self.wc_pg.id] + 1)
        for workcenter in (self.wc_two, self.wc_other, self.wc_2x12):
            self.assertEqual(after[workcenter.id], before[workcenter.id], workcenter.name)
        leave.date_to = self._utc(TUESDAY, 12)
        self.assertEqual(self._stamps()[self.wc_pg.id], before[self.wc_pg.id] + 2)

    def test_r30_global_leave_stamps_every_center_of_the_calendar(self):
        before = self._stamps()
        self._leave(calendar=self.cal_pg)
        after = self._stamps()
        for workcenter in (self.wc_pg, self.wc_two, self.wc_other):
            self.assertEqual(after[workcenter.id], before[workcenter.id] + 1, workcenter.name)
        self.assertEqual(after[self.wc_2x12.id], before[self.wc_2x12.id])

    def test_r30_time_off_leave_does_not_stamp(self):
        """Leave `leave` (отпуск, празник) не е в инварианта — не удря."""
        before = self._stamps()
        leave = self._leave(self.wc_pg, self.cal_pg)
        leave.time_type = "leave"
        after = self._stamps()
        self.assertEqual(after[self.wc_pg.id], before[self.wc_pg.id] + 1)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReview2TrainResilience(CrewLanesCommon):
    """Находка 2 (Р36, Р37): едновременен запис в един център не спира
    часовата задача за другите."""

    def _flaky(self, failures):
        """`_crew_train`, който за wc_pg хвърля SerializationFailure първите
        `failures` пъти (както при оператор, записал същата поръчка)."""
        Workcenter = type(self.env["mrp.workcenter"])
        original = Workcenter._crew_train
        calls = []

        def flaky(workcenters, moment):
            if self.wc_pg in workcenters:
                calls.append(moment)
                if len(calls) <= failures:
                    # Частичен запис преди грешката: трябва да се върне.
                    workcenters.env.cr.execute(
                        SQL(
                            "UPDATE mrp_workorder SET name = 'Crew half-done' "
                            "WHERE workcenter_id = %s",
                            self.wc_pg.id,
                        )
                    )
                    raise errors.SerializationFailure(
                        "could not serialize access due to concurrent update"
                    )
            return original(workcenters, moment)

        return patch.object(Workcenter, "_crew_train", flaky), calls

    def test_r36_concurrency_error_skips_only_that_center(self):
        stale_pg = self._wo(self.wc_pg, MONDAY, 9)
        stale_other = self._wo(self.wc_other, MONDAY, 9)
        self.assertLess(self.wc_pg.id, self.wc_other.id)
        flaky, calls = self._flaky(failures=10)
        with flaky:
            self.env["mrp.workcenter"]._cron_crew_train()
        self.assertEqual(len(calls), 1)
        # Центърът след wc_pg е изтеглен; wc_pg е върнат цял.
        self.assertSlot(stale_other, MONDAY, 11, MONDAY, 12)
        stale_pg.invalidate_recordset()
        self.assertSlot(stale_pg, MONDAY, 9, MONDAY, 10)
        self.assertEqual(stale_pg.name, "Crew operation")

    def test_r36_cron_retries_the_center_and_reports_progress(self):
        stale_pg = self._wo(self.wc_pg, MONDAY, 9)
        stale_other = self._wo(self.wc_other, MONDAY, 9)
        flaky, calls = self._flaky(failures=1)
        Workcenter = type(self.env["mrp.workcenter"])
        progress = []

        # В 18 стъпката минава през _crew_commit_progress (notify + commit).
        def commit_progress(workcenter, done, remaining):
            progress.append((done, remaining))

        with flaky, patch.object(Workcenter, "_crew_commit_progress", commit_progress):
            self.env["mrp.workcenter"].with_context(
                ir_cron_progress_id=-1
            )._cron_crew_train()
        # Вторият опит (след commit-а — свеж снимък) изтегля и wc_pg.
        self.assertEqual(len(calls), 2)
        self.assertSlot(stale_pg, MONDAY, 11, MONDAY, 12)
        self.assertSlot(stale_other, MONDAY, 11, MONDAY, 12)
        # ir_cron._run_job: (успех, done, remaining=0) → FULLY_DONE; без
        # `remaining` редът остава 0 от началото и провал → FAILED.
        self.assertTrue(progress)
        self.assertNotIn(None, [remaining for _processed, remaining in progress])
        self.assertEqual(progress[-1][1], 0)
        remaining = [remaining for _processed, remaining in progress]
        self.assertEqual(remaining, sorted(remaining, reverse=True))
        # Повтореният център се брои: стъпките са центровете + един повтор.
        count = len(self.env["mrp.workcenter"].search([("resource_calendar_id", "!=", False)]))
        self.assertEqual(len(progress), count + 1)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReview2Midnight(CrewLanesCommon):
    """Находка 3 (Р30, Р35): календарът 2x12 (Р28) с ред до 24:00."""

    def test_r30_walk_over_midnight_has_no_microsecond(self):
        x = self._wo(self.wc_2x12, WEDNESDAY, 9, minutes=720)
        result = x.crew_drop(self.wc_2x12.id, 1, date_start=self._utc(MONDAY, 20))
        self.assertEqual(result["status"], "done")
        self.assertEqual(x.date_finished, self._utc(TUESDAY, 8))
        self.assertEqual(x.date_finished.microsecond, 0)
        # Допираща поръчка (както идва от UI/импорт — в цели секунди).
        nxt = self._wo(self.wc_2x12, TUESDAY, 8)
        self.assertSlot(nxt, TUESDAY, 8, TUESDAY, 9)

    def test_r30_lanes_slot_over_midnight_has_no_microsecond(self):
        self.wc_2x12.crew_lane_count = 2
        lane, date_from, date_to = self.wc_2x12._crew_first_slot_lanes(
            self._utc(MONDAY, 20), 720
        )
        self.assertEqual((lane, date_from, date_to), (1, self._utc(MONDAY, 20), self._utc(TUESDAY, 8)))

    def test_r30_stored_microsecond_is_not_an_overlap(self):
        """Заварен край с микросекунда (стандартното „Plan“ на еднопистов
        център пише края на ядрото): M15 сравнява до секунда, като ядрото."""
        a = self._wo(self.wc_2x12, TUESDAY, 4)
        a.with_context(crew_lane_defer=True).write(
            {"date_finished": self._utc(TUESDAY, 5).replace(microsecond=1)}
        )
        b = self._wo(self.wc_2x12, TUESDAY, 5)
        self.assertSlot(b, TUESDAY, 5, TUESDAY, 6)
        # Р32 (07.10): обикновеното създаване би избутало a и b — тук
        # проверката M15 се пуска сама върху заварено застъпване.
        with self.assertRaises(ValidationError):
            self._wo(self.wc_2x12, TUESDAY, 4, 59, overlap=True)._crew_check_lane_overlap()

    def test_r35_train_over_midnight_no_false_note(self):
        mo = self._mo()
        op1 = self._wo(self.wc_2x12, MONDAY, 9, minutes=780, mo=mo, sequence=1)
        op2 = self._wo(self.wc_other, TUESDAY, 1, mo=mo, sequence=2)
        self.assertEqual(op2.blocked_by_workorder_ids, op1)
        self.wc_2x12._crew_train(self._utc(MONDAY, 11))
        self.assertSlot(op1, MONDAY, 11, TUESDAY, 1)
        self.assertFalse(self._notes(mo, "The train did not move it"))
        self.assertFalse(op2.crew_dep_conflict_since)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReview2DropClamp(CrewLanesCommon):
    """Находка 4 (Р32): началото след изтеглянето пак е извън вагоните."""

    def test_r32_now_inside_the_started_goes_after_it(self):
        started = self._wo(self.wc_pg, MONDAY, 10, minutes=120)
        started.state = "progress"
        x = self._wo(self.wc_pg, WEDNESDAY, 9)
        result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(MONDAY, 8))
        self.assertEqual(result["status"], "done")
        self.assertSlot(x, MONDAY, 13, MONDAY, 14)
        self.assertSlot(started, MONDAY, 10, MONDAY, 12)

    # 19.0.1.5.5 (Р33 изменено): само предшественик на СЪЩИЯ център дърпа
    # X — затова тук той е в другата писта на центъра с две писти.
    def test_r32_predecessor_end_inside_a_wagon_keeps_the_order(self):
        mo = self._mo()
        pred = self._wo(self.wc_two, MONDAY, 13, 30, mo=mo, sequence=1, crew_lane=2)
        x = self._wo(self.wc_two, WEDNESDAY, 9, mo=mo, sequence=2)
        self.assertEqual(x.blocked_by_workorder_ids, pred)
        wagon = self._wo(self.wc_two, MONDAY, 14, 15, crew_lane=1)
        result = x.crew_drop(self.wc_two.id, 1, date_start=self._utc(MONDAY, 14))
        self.assertEqual(result["status"], "done")
        self.assertSlot(wagon, MONDAY, 14, MONDAY, 15, minute=15, end_minute=15)
        self.assertSlot(x, MONDAY, 15, MONDAY, 16, minute=15, end_minute=15, second=1)
        self.assertNotIn(wagon.id, [move["id"] for move in result["moves"]])

    def test_r32_predecessor_end_inside_the_started(self):
        mo = self._mo()
        pred = self._wo(self.wc_two, MONDAY, 10, 30, mo=mo, sequence=1, crew_lane=2)
        x = self._wo(self.wc_two, WEDNESDAY, 9, mo=mo, sequence=2)
        started = self._wo(self.wc_two, MONDAY, 11, minutes=60, crew_lane=1)
        started.state = "progress"
        # Пускане в 08:00 → сега (11:00) е в започнатата; X тръгва след нея.
        result = x.crew_drop(self.wc_two.id, 1, date_start=self._utc(MONDAY, 8))
        self.assertEqual(result["status"], "done")
        self.assertEqual(pred.date_finished, self._utc(MONDAY, 11, 30))
        self.assertSlot(x, MONDAY, 13, MONDAY, 14)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReview2ManualDuration(CrewLanesCommon):
    """Находка 5 (Р37): ръчно отчетено време стартира поръчката."""

    def setUp(self):
        super().setUp()
        self.wc_pg.write(
            {"crew_max_stretch_hours": 1.0, "crew_responsible_id": self.mrp_user.id}
        )

    def test_r37_manual_duration_is_a_start(self):
        wo = self._wo(self.wc_pg, MONDAY, 9)
        wo.duration = 30
        self.assertEqual(wo.state, "progress")
        self.assertTrue(wo.time_ids)
        self.assertEqual(wo.crew_planned_finish, self._utc(MONDAY, 10))
        # Пн 10–12 + 13–17 + вт 08–12 + 13–16 = 13 работни часа.
        self.wc_pg._crew_stretch_alarm(self._utc(TUESDAY, 16))
        self.assertAlmostEqual(wo.crew_stretch_hours, 13.0, places=4)
        self.assertEqual(wo.crew_stretch_alert_level, 13)
        self.assertTrue(self._notes(wo.production_id, "past its planned end"))
        # M14.4 е минал целия: съобщението `changed` със source = start.
        started = [
            payload
            for _channel, payload in self._bus("mrp_crew_lane/changed")
            if payload["source"] == "start" and wo.id in payload["workorder_ids"]
        ]
        self.assertEqual(len(started), 1)
