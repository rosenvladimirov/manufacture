# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Тестове 11–22 от TECH_DESIGN §9.8: пистите, забраната за застъпване,
стандартното планиране с писти, двигателят, „пусни тук“, зависимостите,
влакът, тревогата, ключалката и шината, миграцията, Гантът.

Календарът е този на Полигруп (08–12, обяд 12–13, 13–17 всеки ден,
Europe/Sofia); „сега“ е понеделник 05.10.2026 11:00 местно време."""
import json
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock, patch

from freezegun import freeze_time
from pytz import utc

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged

from .common import MONDAY, CrewWorkorderCommon

TUESDAY = MONDAY + timedelta(days=1)
WEDNESDAY = MONDAY + timedelta(days=2)
FRIDAY = MONDAY - timedelta(days=3)
# 05.10.2026 11:00 в София (UTC+3).
FROZEN_NOW = "2026-10-05 08:00:00"


class CrewLanesCommon(CrewWorkorderCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wc_two = cls._make_workcenter("WC Two Lanes", cls.cal_pg)
        cls.wc_two.crew_lane_count = 2
        cls.wc_other = cls._make_workcenter("WC Other Machine", cls.cal_pg)
        cls.Batch = cls.env["mrp.workcenter.replan.batch"]
        cls.Lock = cls.env["mrp.workcenter.lane.lock"]
        cls.crew12 = cls.emp1 | cls.emp2
        cls.mrp_user = new_test_user(
            cls.env,
            login="crew_lanes_user",
            email="crew_lanes_user@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.mrp_user2 = new_test_user(
            cls.env,
            login="crew_lanes_user2",
            email="crew_lanes_user2@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )

    # --- помощни -----------------------------------------------------------

    def _mo(self, date_start=None):
        vals = {"product_id": self.product.id, "product_qty": 1.0}
        if date_start:
            vals["date_start"] = date_start
        mo = self.env["mrp.production"].create(vals)
        mo.action_confirm()
        return mo

    def _wo(self, workcenter, day, hour, minute=0, minutes=60.0, mo=None, **extra):
        """Поръчка на потвърдена МО с начало в местен час."""
        return self._make_wo(
            workcenter,
            self._utc(day, hour, minute),
            minutes=minutes,
            mo=mo or self._mo(),
            **extra,
        )

    def assertSlot(self, wo, day, hour, end_day, end_hour, minute=0, end_minute=0, second=0):
        # `second` — секундите разлика в началото (CREW_GAP, Росен 12.10.2026):
        # поръчка, сложена веднага след друга, почва секунда след края ѝ;
        # краят ѝ не се мести.
        self.assertEqual(
            (wo.date_start, wo.date_finished),
            (
                self._utc(day, hour, minute) + timedelta(seconds=second),
                self._utc(end_day, end_hour, end_minute),
            ),
            wo.display_name,
        )

    @contextmanager
    def assertRaisesText(self, exception, text):
        """Като assertRaisesRegex, но през assertRaises на Odoo — със
        savepoint и rollback (иначе частичният запис остава в теста)."""
        with self.assertRaises(exception) as catcher:
            yield catcher
        self.assertIn(text, str(catcher.exception))

    def _bus(self, kind):
        """Съобщенията по шината от този тест: flush пуска precommit и
        записва редовете в bus.bus (К13)."""
        self.env.cr.flush()
        result = []
        for row in self.env["bus.bus"].sudo().search([], order="id"):
            message = json.loads(row.message)
            if message["type"] == kind:
                result.append((json.loads(row.channel), message["payload"]))
        return result

    def _notes(self, production, text):
        return production.message_ids.filtered(lambda m: text in (m.body or ""))


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLaneFields(CrewLanesCommon):
    """11. Полетата на центъра (Р29, Р37)."""

    def test_11_1_one_lane_by_default(self):
        self.assertEqual(self.wc_pg.crew_lane_count, 1)
        wo = self._wo(self.wc_pg, TUESDAY, 9)
        self.assertEqual(wo.crew_lane, 1)

    def test_11_2_bounds(self):
        for value in (0, 21):
            with self.assertRaises(ValidationError):
                self.wc_pg.crew_lane_count = value
        self.wc_pg.crew_lane_count = 20
        self.assertEqual(self.wc_pg.crew_lane_count, 20)

    def test_11_3_decrease_below_busy_lane(self):
        wo = self._wo(self.wc_two, TUESDAY, 9, crew_lane=2)
        with self.assertRaisesText(ValidationError, "higher lane"):
            self.wc_two.crew_lane_count = 1
        self.assertEqual(self.wc_two.crew_lane_count, 2)
        wo.state = "done"
        self.wc_two.crew_lane_count = 1

    def test_11_4_mrp_user_cannot_write(self):
        for vals in (
            {"crew_lane_count": 2},
            {"crew_responsible_id": self.mrp_user.id},
            {"crew_max_stretch_hours": 2.0},
        ):
            with self.assertRaises(AccessError):
                self.wc_pg.with_user(self.mrp_user).write(vals)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLaneOverlap(CrewLanesCommon):
    """12. Р30: две поръчки в една писта никога не се застъпват (M13/M15)."""

    def test_12_1_overlap_never_stays(self):
        """Р30 + Р32 (изменено 07.10): създаване върху незапочната я
        избутва след себе си — застъпване не остава."""
        first = self._wo(self.wc_pg, TUESDAY, 9)
        second = self._wo(self.wc_pg, TUESDAY, 9, 30)
        self.assertSlot(second, TUESDAY, 9, TUESDAY, 10, minute=30, end_minute=30)
        self.assertSlot(first, TUESDAY, 10, TUESDAY, 11, minute=30, end_minute=30, second=1)

    def test_12_2_touching_passes(self):
        first = self._wo(self.wc_pg, TUESDAY, 9)
        second = self._wo(self.wc_pg, TUESDAY, 10)
        self.assertEqual(first.date_finished, second.date_start)

    def test_12_3_different_lanes_pass(self):
        first = self._wo(self.wc_two, TUESDAY, 9)
        second = self._wo(self.wc_two, TUESDAY, 9, crew_lane=2)
        self.assertEqual((first.crew_lane, second.crew_lane), (1, 2))

    def test_12_4_one_lane_standard_write_pushes(self):
        """Р32 (изменено 07.10): стандартният запис върху незапочната я
        избутва; върху започната — отказ, нищо не се мести."""
        first = self._wo(self.wc_pg, TUESDAY, 9)
        other = self._wo(self.wc_pg, TUESDAY, 11)
        other.write(
            {
                "date_start": self._utc(TUESDAY, 9, 30),
                "date_finished": self._utc(TUESDAY, 10, 30),
            }
        )
        self.assertSlot(other, TUESDAY, 9, TUESDAY, 10, minute=30, end_minute=30)
        self.assertSlot(first, TUESDAY, 10, TUESDAY, 11, minute=30, end_minute=30, second=1)
        running = self._wo(self.wc_pg, TUESDAY, 14)
        running.state = "progress"
        with self.assertRaisesText(UserError, "started work order"):
            other.write(
                {
                    "date_start": self._utc(TUESDAY, 14, 30),
                    "date_finished": self._utc(TUESDAY, 15, 30),
                }
            )
        self.assertSlot(other, TUESDAY, 9, TUESDAY, 10, minute=30, end_minute=30)

    def test_12_5_two_started_pass(self):
        first = self._wo(self.wc_pg, TUESDAY, 9)
        first.state = "progress"
        second = self._wo(self.wc_pg, TUESDAY, 9, 30, state="progress")
        self.assertEqual(second.state, "progress")
        # Р32 (07.10): незапочната върху започнати — започнатите не се
        # избутват, затова отказ.
        with self.assertRaisesText(UserError, "started work order"):
            self._wo(self.wc_pg, TUESDAY, 9, 45)
        # Без избутване (под crew_lane_defer на викащия) Р30 пак държи.
        with self.assertRaisesText(ValidationError, "never overlap"):
            self.WO.with_context(crew_lane_defer=True).create(
                {
                    "name": "Crew deferred",
                    "workcenter_id": self.wc_pg.id,
                    "production_id": self._mo().id,
                    "product_uom_id": self.product.uom_id.id,
                    "duration_expected": 60,
                    "date_start": self._utc(TUESDAY, 9, 45),
                    "date_finished": self._utc(TUESDAY, 10, 45),
                }
            )._crew_check_lane_overlap()

    def test_12_6_done_not_in_the_invariant(self):
        first = self._wo(self.wc_pg, TUESDAY, 9)
        first.state = "done"
        second = self._wo(self.wc_pg, TUESDAY, 9)
        self.assertEqual(second.crew_lane, 1)

    def _free_leave(self, start, stop):
        return self.env["resource.calendar.leaves"].create(
            {
                "name": "Crew maintenance window",
                "calendar_id": self.cal_pg.id,
                "resource_id": self.wc_pg.resource_id.id,
                "date_from": start,
                "date_to": stop,
                "time_type": "other",
            }
        )

    def test_12_7_free_leave_both_ways(self):
        self._free_leave(self._utc(TUESDAY, 9), self._utc(TUESDAY, 10))
        with self.assertRaisesText(ValidationError, "Crew maintenance window"):
            self._wo(self.wc_pg, TUESDAY, 9, 30)
        self._wo(self.wc_pg, TUESDAY, 13)
        with self.assertRaisesText(ValidationError, "not started"):
            self._free_leave(self._utc(TUESDAY, 13, 30), self._utc(TUESDAY, 14, 30))
        # Започнатата не е засегната от забраната (М13).
        started = self._wo(self.wc_pg, TUESDAY, 15, state="progress")
        self._free_leave(self._utc(TUESDAY, 15, 30), self._utc(TUESDAY, 16))
        self.assertEqual(started.state, "progress")

    def test_12_8_direct_leave_write(self):
        self._wo(self.wc_pg, TUESDAY, 9)
        other = self._wo(self.wc_pg, TUESDAY, 11)
        other.leave_id.write(
            {"date_from": self._utc(TUESDAY, 13), "date_to": self._utc(TUESDAY, 14)}
        )
        self.assertSlot(other, TUESDAY, 13, TUESDAY, 14)
        with self.assertRaisesText(ValidationError, "never overlap"):
            other.leave_id.write(
                {
                    "date_from": self._utc(TUESDAY, 9, 30),
                    "date_to": self._utc(TUESDAY, 10, 30),
                }
            )

    def test_12_9_create_load_copy(self):
        first = self._wo(self.wc_pg, TUESDAY, 9)
        mo = self._mo()
        result = self.WO.with_context(tz="UTC").load(
            [
                "name",
                "workcenter_id/.id",
                "production_id/.id",
                "product_uom_id/.id",
                "duration_expected",
                "date_start",
                "date_finished",
            ],
            [
                [
                    "Crew loaded",
                    str(self.wc_pg.id),
                    str(mo.id),
                    str(self.product.uom_id.id),
                    "60",
                    fields.Datetime.to_string(self._utc(TUESDAY, 9, 30)),
                    fields.Datetime.to_string(self._utc(TUESDAY, 10, 30)),
                ]
            ],
        )
        # Р32 (изменено 07.10): импортът е запис извън Ганта — избутва
        # незапочнатата след себе си, вместо да откаже.
        self.assertEqual(len(result["ids"]), 1, result["messages"])
        loaded = self.WO.browse(result["ids"])
        self.assertSlot(loaded, TUESDAY, 9, TUESDAY, 10, minute=30, end_minute=30)
        self.assertSlot(first, TUESDAY, 10, TUESDAY, 11, minute=30, end_minute=30, second=1)
        # Върху започната импортът се отказва (ясно съобщение).
        loaded.state = "progress"
        result = self.WO.with_context(tz="UTC").load(
            [
                "name",
                "workcenter_id/.id",
                "production_id/.id",
                "product_uom_id/.id",
                "duration_expected",
                "date_start",
                "date_finished",
            ],
            [
                [
                    "Crew loaded 2",
                    str(self.wc_pg.id),
                    str(self._mo().id),
                    str(self.product.uom_id.id),
                    "60",
                    fields.Datetime.to_string(self._utc(TUESDAY, 9)),
                    fields.Datetime.to_string(self._utc(TUESDAY, 10)),
                ]
            ],
        )
        self.assertFalse(result["ids"])
        self.assertIn(
            "started work order", " ".join(m["message"] for m in result["messages"])
        )
        copied = first.copy(
            {"date_start": first.date_start, "date_finished": first.date_finished}
        )
        self.assertSlot(copied, TUESDAY, 10, TUESDAY, 11, minute=30, end_minute=30, second=1)
        self.assertSlot(first, TUESDAY, 11, TUESDAY, 13, minute=30, end_minute=30, second=1)

    def test_12_10_legacy_overlap(self):
        first = self._wo(self.wc_pg, TUESDAY, 9)
        second = self._wo(self.wc_pg, TUESDAY, 9, 30, overlap=True)
        # Несвързан запис минава; изваждането от застъпването — също.
        second.write({"name": "Crew renamed"})
        first.write({"name": "Crew renamed too"})
        second.write(
            {"date_start": self._utc(TUESDAY, 13), "date_finished": self._utc(TUESDAY, 14)}
        )
        self.assertSlot(second, TUESDAY, 13, TUESDAY, 14)

    def test_12_11_lane_3_to_one_lane_center(self):
        self.wc_two.crew_lane_count = 3
        wo = self._wo(self.wc_two, TUESDAY, 9, crew_lane=3)
        wo.write({"workcenter_id": self.wc_pg.id})
        self.assertEqual((wo.workcenter_id, wo.crew_lane), (self.wc_pg, 1))


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLanePlanning(CrewLanesCommon):
    """13. Стандартното планиране с N писти (M14)."""

    def test_13_1_one_lane_is_standard(self):
        self._wo(self.wc_pg, TUESDAY, 8)
        start = self._utc(TUESDAY, 8)
        ours = self.wc_pg._get_first_available_slot(start, 60)
        standard = self.wc_pg.with_context(crew_lane_raw=True)._get_first_available_slot(
            start, 60
        )
        self.assertEqual(ours, standard)
        self.assertEqual(ours, (self._utc(TUESDAY, 9), self._utc(TUESDAY, 10)))

    def test_13_2_plan_two_lanes(self):
        workorders = self.WO
        for _i in range(3):
            mo = self._mo(date_start=self._utc(TUESDAY, 8))
            workorders |= self.WO.create(
                {
                    "name": "Crew planned",
                    "workcenter_id": self.wc_two.id,
                    "production_id": mo.id,
                    "product_uom_id": self.product.uom_id.id,
                    "duration_expected": 60.0,
                }
            )
        for wo in workorders:
            wo._plan_workorder()
        first, second, third = workorders
        self.assertSlot(first, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(second, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(third, TUESDAY, 9, TUESDAY, 10)
        self.assertEqual(
            (first.crew_lane, second.crew_lane, third.crew_lane), (1, 2, 1)
        )

    def test_13_3_ee_reschedule_sees_lanes(self):
        self._wo(self.wc_two, TUESDAY, 8)
        moved = self._wo(self.wc_two, WEDNESDAY, 8)
        dates = moved._web_gantt_reschedule_compute_dates(
            self._utc(TUESDAY, 8), True, "date_start", "date_finished"
        )
        self.assertEqual(dates, [self._utc(TUESDAY, 8), self._utc(TUESDAY, 9)])
        self._wo(self.wc_pg, TUESDAY, 8)
        single = self._wo(self.wc_pg, WEDNESDAY, 8)
        dates = single._web_gantt_reschedule_compute_dates(
            self._utc(TUESDAY, 8), True, "date_start", "date_finished"
        )
        self.assertEqual(dates, [self._utc(TUESDAY, 9), self._utc(TUESDAY, 10)])

    def test_13_4_resolve_jumps_to_free_lane(self):
        self._wo(self.wc_two, TUESDAY, 8)
        wo = self._wo(self.wc_two, WEDNESDAY, 8)
        wo.write({"date_start": self._utc(TUESDAY, 8), "date_finished": self._utc(TUESDAY, 9)})
        self.assertEqual(wo.crew_lane, 2)
        self.assertSlot(wo, TUESDAY, 8, TUESDAY, 9)

    def test_13_5_button_start_pushes(self):
        """Ранният старт в 11:00 мести X на 11–12; незапочнатата Y (11:30)
        се избутва през обяда на 13–14; планираният край е 12:00."""
        x = self._wo(self.wc_pg, MONDAY, 13)
        y = self._wo(self.wc_pg, MONDAY, 11, 30)
        x.button_start(bypass=True)
        self.assertEqual(x.state, "progress")
        self.assertSlot(x, MONDAY, 11, MONDAY, 12)
        self.assertEqual(x.crew_planned_finish, self._utc(MONDAY, 12))
        self.assertSlot(y, MONDAY, 13, MONDAY, 14)
        batch = self.Batch.search([("source", "=", "train")], limit=1)
        self.assertIn(y, batch.line_ids.workorder_id)

    def test_13_5_button_start_overflow(self):
        """Една писта, заета от започната: стартът не се отказва, а МО
        получава бележка „Lane overflow“."""
        running = self._wo(self.wc_pg, MONDAY, 10, 30)
        running.state = "progress"
        x = self._wo(self.wc_pg, MONDAY, 13)
        x.button_start(bypass=True)
        self.assertEqual(x.state, "progress")
        self.assertEqual(x.crew_lane, 1)
        self.assertTrue(self._notes(x.production_id, "Lane overflow"))

    def test_13_6_one_crew_for_all_lanes(self):
        self._roster(self.wc_two, TUESDAY, "08:00", self.crew12)
        first = self._wo(self.wc_two, TUESDAY, 9)
        second = self._wo(self.wc_two, TUESDAY, 9, crew_lane=2)
        self.assertEqual(first.employee_assigned_ids, self.crew12)
        self.assertEqual(second.employee_assigned_ids, self.crew12)

    def test_13_7_progress_bar_times_lanes(self):
        start = utc.localize(self._utc(TUESDAY, 0))
        stop = utc.localize(self._utc(WEDNESDAY, 0))
        bar = self.WO._web_gantt_progress_bar_workcenter_id(
            [self.wc_pg.id, self.wc_two.id], start, stop
        )
        self.assertAlmostEqual(bar[self.wc_pg.id]["max_value"], 8.0)
        self.assertAlmostEqual(bar[self.wc_two.id]["max_value"], 16.0)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLaneEngine(CrewLanesCommon):
    """14. Двигателят (M6) с писти."""

    def _run(self, workcenter):
        return self.Batch._crew_run(
            {
                "workcenter_ids": [workcenter.id],
                "date_from": MONDAY,
                "date_to": MONDAY + timedelta(days=14),
                "only_stale": True,
            },
            "recompute",
        )

    def test_14_1_earliest_free_lane(self):
        self._wo(self.wc_two, MONDAY, 11)
        stale = self._wo(self.wc_two, FRIDAY, 9)
        self._run(self.wc_two)
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertEqual(stale.crew_lane, 2)

    def test_14_2_started_blocks_only_its_lane(self):
        running = self._wo(self.wc_two, MONDAY, 9)
        running.state = "progress"
        stale = self._wo(self.wc_two, FRIDAY, 9)
        self._run(self.wc_two)
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertEqual(stale.crew_lane, 2)

    def test_14_3_lane_in_the_batch(self):
        self._wo(self.wc_two, MONDAY, 11)
        stale = self._wo(self.wc_two, FRIDAY, 9)
        batch = self._run(self.wc_two)
        line = batch.line_ids.filtered(lambda line: line.workorder_id == stale)
        self.assertEqual((line.old_lane, line.new_lane), (1, 2))


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestCrewDrop(CrewLanesCommon):
    """15. M17 „пусни тук“ (Р32)."""

    def test_15_1_insert_pushes_the_chain(self):
        a = self._wo(self.wc_pg, TUESDAY, 8)
        b = self._wo(self.wc_pg, TUESDAY, 9)
        c = self._wo(self.wc_pg, TUESDAY, 10)
        d = self._wo(self.wc_pg, TUESDAY, 14)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        result = x.crew_drop(self.wc_pg.id, 1, after_workorder_id=a.id)
        self.assertEqual(result["status"], "done")
        self.assertSlot(a, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(x, TUESDAY, 9, TUESDAY, 10, second=1)
        self.assertSlot(b, TUESDAY, 10, TUESDAY, 11, second=1)
        self.assertSlot(c, TUESDAY, 11, TUESDAY, 12, second=1)
        self.assertSlot(d, TUESDAY, 14, TUESDAY, 15)
        reasons = {m["id"]: m["reason"] for m in result["moves"]}
        self.assertEqual(reasons, {x.id: "drop", b.id: "chain", c.id: "chain"})

    def test_15_2_length_kept_over_the_night(self):
        x = self._wo(self.wc_pg, WEDNESDAY, 8, minutes=240.0)
        x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(MONDAY, 16))
        self.assertSlot(x, MONDAY, 16, TUESDAY, 11)
        self.assertEqual(x.duration_expected, 240.0)

    def test_15_3_started_in_the_chain_refuses(self):
        a = self._wo(self.wc_pg, TUESDAY, 8)
        b = self._wo(self.wc_pg, TUESDAY, 9)
        b.state = "progress"
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        with self.assertRaisesText(UserError, "started work order"):
            x.crew_drop(self.wc_pg.id, 1, after_workorder_id=a.id)
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(b, TUESDAY, 9, TUESDAY, 10)
        self.assertFalse(self.Batch.search([("source", "=", "drop")]))

    def test_15_4_past_becomes_now(self):
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(MONDAY, 9))
        self.assertSlot(x, MONDAY, 11, MONDAY, 12)
        self.assertTrue(result["notes"])

    def test_15_5_after_the_predecessor(self):
        """Предшественик на СЪЩИЯ център (друга писта) дърпа X след себе
        си. (На друг център — не, от 1.5.5: Р33 изменено, конфликтът мига —
        test_lanes_dep_conflict.)"""
        mo = self._mo()
        pred = self._wo(self.wc_two, TUESDAY, 10, mo=mo, sequence=1, crew_lane=2)
        x = self._wo(self.wc_two, WEDNESDAY, 8, mo=mo, sequence=2)
        self.assertEqual(x.blocked_by_workorder_ids, pred)
        result = x.crew_drop(self.wc_two.id, 1, date_start=self._utc(TUESDAY, 8))
        self.assertSlot(x, TUESDAY, 11, TUESDAY, 12)
        self.assertTrue(any(pred.display_name in note for note in result["notes"]))
        self.assertFalse(x.crew_dep_conflict)

    def test_15_6_other_lane(self):
        a = self._wo(self.wc_two, TUESDAY, 8)
        x = self._wo(self.wc_two, WEDNESDAY, 8)
        x.crew_drop(self.wc_two.id, 2, date_start=self._utc(TUESDAY, 8))
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9)
        self.assertEqual(x.crew_lane, 2)
        self.assertSlot(a, TUESDAY, 8, TUESDAY, 9)

    def test_15_7b_duration_per_machine(self):
        """19.0.1.9.0 (Росен 12.10.2026): минутите на поръчката на всяка от
        машините ѝ — по тях Гантът разпъва картинката докато се дърпа; на
        по-бавната алтернатива пускането взима точно тях."""
        self.wc_other.time_efficiency = 50.0
        self.wc_pg.alternative_workcenter_ids = self.wc_other
        # С операция: без нея времето е въведено на ръка и ядрото не го
        # мени по друг център.
        bom = self.env["mrp.bom"].create(
            {"product_tmpl_id": self.product.product_tmpl_id.id, "product_qty": 1.0}
        )
        operation = self.env["mrp.routing.workcenter"].create(
            {
                "name": "Crew step",
                "bom_id": bom.id,
                "workcenter_id": self.wc_pg.id,
                "time_mode": "manual",
                "time_cycle_manual": 60.0,
            }
        )
        x = self._wo(self.wc_pg, WEDNESDAY, 8, operation_id=operation.id)
        durations = x.crew_center_durations
        self.assertAlmostEqual(durations[str(self.wc_pg.id)], 60.0)
        self.assertAlmostEqual(durations[str(self.wc_other.id)], 120.0)
        x.crew_drop(self.wc_other.id, 1, date_start=self._utc(TUESDAY, 8))
        self.assertAlmostEqual(x.duration_expected, 120.0)
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 10)
        x.state = "cancel"
        self.assertFalse(x.crew_center_durations)

    def test_15_7_other_machine(self):
        """Друга машина: свободна дупка минава с пресметнатата
        продължителност; заета → отказ (В1)."""
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        x.crew_drop(self.wc_other.id, 1, date_start=self._utc(TUESDAY, 8))
        self.assertEqual(x.workcenter_id, self.wc_other)
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9)
        self.assertEqual(
            x.duration_expected, x._get_duration_expected(alternative_workcenter=self.wc_other)
        )
        self.assertEqual(x.leave_id.resource_id, self.wc_other.resource_id)
        busy = self._wo(self.wc_other, TUESDAY, 10)
        x2 = self._wo(self.wc_pg, WEDNESDAY, 10)
        with self.assertRaisesText(UserError, "No free lane"):
            x2.crew_drop(self.wc_other.id, 1, date_start=self._utc(TUESDAY, 10))
        self.assertEqual(x2.workcenter_id, self.wc_pg)
        self.assertSlot(busy, TUESDAY, 10, TUESDAY, 11)

    def test_15_8_lock(self):
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        self.Lock.with_user(self.mrp_user2)._crew_lane_take(self.wc_pg, 1)
        with self.assertRaisesText(UserError, "being moved by"):
            x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8))
        self.Lock.search([]).unlink()
        self.Lock._crew_lane_take(self.wc_pg, 1)
        x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8))
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9)
        self.assertFalse(self.Lock.search([("user_id", "=", self.env.uid)]), "освободена")

    def test_15_9_mo_force_date(self):
        mo = self._mo()
        x = self._wo(self.wc_pg, WEDNESDAY, 8, mo=mo)
        x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8))
        self.assertTrue(mo.is_planned)
        self.assertEqual(
            (mo.date_start, mo.date_finished),
            (self._utc(TUESDAY, 8), self._utc(TUESDAY, 9)),
        )

    def test_15_10_batch_and_undo(self):
        a = self._wo(self.wc_two, TUESDAY, 8)
        b = self._wo(self.wc_two, TUESDAY, 9)
        x = self._wo(self.wc_two, WEDNESDAY, 8, crew_lane=2)
        result = x.crew_drop(self.wc_two.id, 1, after_workorder_id=a.id)
        batch = self.Batch.browse(result["batch_id"])
        self.assertEqual(batch.source, "drop")
        self.assertEqual((x.crew_lane, b.crew_lane), (1, 1))
        self.assertSlot(x, TUESDAY, 9, TUESDAY, 10, second=1)
        self.assertSlot(b, TUESDAY, 10, TUESDAY, 11, second=1)
        line = batch.line_ids.filtered(lambda line: line.workorder_id == x)
        self.assertEqual((line.old_lane, line.new_lane, line.reason), (2, 1, "drop"))
        batch.action_undo()
        self.assertEqual(batch.state, "undone")
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertEqual(x.crew_lane, 2)
        self.assertSlot(b, TUESDAY, 9, TUESDAY, 10)
        self.assertEqual(b.crew_lane, 1)
        with self.assertRaises(UserError):
            batch.action_undo()

    def test_15_10_undo_only_author_or_manager(self):
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8))
        batch = self.Batch.browse(result["batch_id"])
        with self.assertRaises(AccessError):
            batch.with_user(self.mrp_user).action_undo()

    def test_15_11_bus_changed(self):
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8))
        messages = self._bus("mrp_crew_lane/changed")
        self.assertTrue(messages)
        channel, payload = messages[-1]
        self.assertEqual(
            channel, [self.env.cr.dbname, "res.company", self.company.id, "mrp_crew_lane"]
        )
        self.assertEqual(payload["source"], "drop")
        self.assertIn(x.id, payload["workorder_ids"])

    def test_15_12_inside_a_wagon(self):
        self._wo(self.wc_pg, TUESDAY, 8, minutes=120.0)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 9))
        self.assertSlot(x, TUESDAY, 10, TUESDAY, 11, second=1)

    def test_15_13_drop_sees_the_train(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(MONDAY, 13))
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertSlot(x, MONDAY, 13, MONDAY, 14)
        batch = self.Batch.browse(result["batch_id"])
        line = batch.line_ids.filtered(lambda line: line.workorder_id == stale)
        self.assertEqual(line.reason, "train")


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestDragGuard(CrewLanesCommon):
    """M16 (С11): под флага на влаченето започнатата поръчка не сменя
    начало, център и писта, а краят ѝ се разтяга (M14.5); чужда ключалка
    на източника или целта спира записа; MRP User пуска с `crew_drop`."""

    def test_started_cannot_move_but_stretches(self):
        running = self._wo(self.wc_pg, MONDAY, 10)
        running.state = "progress"
        running.crew_planned_finish = running.date_finished
        drag = running.with_context(crew_gantt_drag=True)
        with self.assertRaisesText(UserError, "cannot be moved"):
            drag.write(
                {"date_start": self._utc(MONDAY, 13), "date_finished": self._utc(MONDAY, 14)}
            )
        with self.assertRaisesText(UserError, "cannot be moved"):
            drag.write({"workcenter_id": self.wc_other.id})
        drag.write({"date_finished": self._utc(MONDAY, 12)})
        self.assertSlot(running, MONDAY, 10, MONDAY, 12)
        self.assertEqual(running.crew_planned_finish, self._utc(MONDAY, 12))

    def test_drag_respects_the_lock(self):
        wo = self._wo(self.wc_pg, TUESDAY, 9)
        self.Lock.with_user(self.mrp_user2)._crew_lane_take(self.wc_other, 1)
        with self.assertRaisesText(UserError, "being moved by"):
            wo.with_context(crew_gantt_drag=True).write(
                {"workcenter_id": self.wc_other.id}
            )
        self.assertEqual(wo.workcenter_id, self.wc_pg)

    def test_mrp_user_drops(self):
        a = self._wo(self.wc_pg, TUESDAY, 8)
        b = self._wo(self.wc_pg, TUESDAY, 9)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        result = x.with_user(self.mrp_user).crew_drop(
            self.wc_pg.id, 1, after_workorder_id=a.id
        )
        batch = self.Batch.browse(result["batch_id"])
        self.assertEqual(batch.user_id, self.mrp_user)
        self.assertSlot(x, TUESDAY, 9, TUESDAY, 10, second=1)
        self.assertSlot(b, TUESDAY, 10, TUESDAY, 11, second=1)
        batch.with_user(self.mrp_user).action_undo()
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestCrewDropDependencies(CrewLanesCommon):
    """16. Р33 (изменено 07.10, 19.0.1.5.5): зависимата на друг център НЕ
    спира пускането (без питане и без отказ) и НЕ се избутва — двете
    поръчки са в конфликт (`crew_dep_conflict`) и мигат, докато датите не
    се оправят. Зависимата на същия център се избутва както досега."""

    def setUp(self):
        super().setUp()
        self.mo = self._mo()
        self.x = self._wo(self.wc_pg, MONDAY, 13, mo=self.mo, sequence=1)
        self.n = self._wo(self.wc_other, MONDAY, 14, mo=self.mo, sequence=2)
        self.assertEqual(self.n.blocked_by_workorder_ids, self.x)

    def _drop(self):
        return self.x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(MONDAY, 14))

    def test_16_1_moves_without_consent_and_does_not_push(self):
        self.assertFalse(self.x.crew_dep_conflict or self.n.crew_dep_conflict)
        result = self._drop()
        self.assertEqual(result["status"], "done")
        self.assertSlot(self.x, MONDAY, 14, MONDAY, 15)
        # Зависимата стои — не е избутана.
        self.assertSlot(self.n, MONDAY, 14, MONDAY, 15)
        self.assertNotIn(self.n.id, [move["id"] for move in result["moves"]])
        batch = self.Batch.browse(result["batch_id"])
        self.assertEqual(batch.line_ids.workorder_id, self.x)
        # И двете са в конфликт; отговорът го казва.
        self.assertTrue(self.x.crew_dep_conflict)
        self.assertTrue(self.n.crew_dep_conflict)
        self.assertTrue(
            any(
                self.n.display_name in note and self.x.display_name in note
                for note in result["notes"]
            ),
            result["notes"],
        )

    def test_16_2_fixing_the_dates_clears_the_flag(self):
        self._drop()
        self.assertTrue(self.n.crew_dep_conflict)
        self.n.write(
            {"date_start": self._utc(MONDAY, 15), "date_finished": self._utc(MONDAY, 16)}
        )
        self.assertFalse(self.x.crew_dep_conflict)
        self.assertFalse(self.n.crew_dep_conflict)

    def test_16_3_started_dependency_does_not_refuse(self):
        self.n.state = "progress"
        result = self._drop()
        self.assertEqual(result["status"], "done")
        self.assertSlot(self.x, MONDAY, 14, MONDAY, 15)
        self.assertSlot(self.n, MONDAY, 14, MONDAY, 15)
        self.assertTrue(self.n.crew_dep_conflict)

    def test_16_4_same_center_dependency_is_still_pushed(self):
        mo = self._mo()
        x = self._wo(self.wc_two, MONDAY, 13, mo=mo, sequence=1)
        n = self._wo(self.wc_two, MONDAY, 14, mo=mo, sequence=2, crew_lane=2)
        self.assertEqual(n.blocked_by_workorder_ids, x)
        result = x.crew_drop(self.wc_two.id, 1, date_start=self._utc(MONDAY, 14))
        self.assertSlot(x, MONDAY, 14, MONDAY, 15)
        self.assertSlot(n, MONDAY, 15, MONDAY, 16)
        reasons = {m["id"]: m["reason"] for m in result["moves"]}
        self.assertEqual(reasons[n.id], "dependency")
        self.assertFalse(x.crew_dep_conflict or n.crew_dep_conflict)

    def test_16_5_validation_error_rolls_back(self):
        """Твърдо правило на друг модул (ValidationError при запис) пак
        отказва цялото пускане с ясно съобщение."""
        WorkOrder = type(self.env["mrp.workorder"])
        original = WorkOrder.write
        x_id = self.x.id

        def write(records, vals):
            if x_id in records.ids and "date_start" in vals:
                raise ValidationError("Extrusion must end before packaging")
            return original(records, vals)

        with patch.object(WorkOrder, "write", write):
            with self.assertRaisesText(ValidationError, "Extrusion") as catcher:
                self._drop()
        self.assertIn("Moving %s was refused" % self.x.display_name, str(catcher.exception))
        self.assertSlot(self.x, MONDAY, 13, MONDAY, 14)
        self.assertSlot(self.n, MONDAY, 14, MONDAY, 15)
        self.assertFalse(self.Batch.search([("source", "=", "drop")]))


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestCrewTrain(CrewLanesCommon):
    """17. Влакът (Р34–Р36, M18)."""

    def _train(self, day=MONDAY, hour=11, minute=0):
        self.wc_pg._crew_train(self._utc(day, hour, minute))

    def _batches(self):
        return self.Batch.search(
            [("source", "=", "train"), ("workcenter_ids", "in", self.wc_pg.ids)]
        )

    def test_17_1_left_pull(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        nxt = self._wo(self.wc_pg, MONDAY, 11, 30)
        self._train()
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertSlot(nxt, MONDAY, 13, MONDAY, 14)
        self.assertEqual((stale.duration_expected, nxt.duration_expected), (60.0, 60.0))

    def test_17_2_right_pull(self):
        running = self._wo(self.wc_pg, MONDAY, 9)
        running.state = "progress"
        self._train()
        self.assertSlot(running, MONDAY, 9, MONDAY, 11)
        self.assertEqual(running.duration_expected, 60.0)

    def test_17_3_calendar_break(self):
        stale = self._wo(self.wc_pg, MONDAY, 9, minutes=120.0)
        self._train(hour=16, minute=30)
        self.assertSlot(stale, MONDAY, 16, TUESDAY, 9, minute=30, end_minute=30)

    def test_17_4_started_is_skipped(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        running = self._wo(self.wc_pg, MONDAY, 11)
        running.state = "progress"
        self._train()
        self.assertSlot(stale, MONDAY, 13, MONDAY, 14)
        self.assertSlot(running, MONDAY, 11, MONDAY, 12)

    def test_17_5_chain_stops_at_the_gap(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        later = self._wo(self.wc_pg, MONDAY, 15)
        self._train()
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertSlot(later, MONDAY, 15, MONDAY, 16)

    def test_17_6_dependency_note_once(self):
        mo = self._mo()
        stale = self._wo(self.wc_pg, MONDAY, 9, mo=mo, sequence=1)
        successor = self._wo(self.wc_other, MONDAY, 11, 30, mo=mo, sequence=2)
        self._train()
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertSlot(successor, MONDAY, 11, MONDAY, 12, minute=30, end_minute=30)
        text = "The train did not move it"
        self.assertEqual(len(self._notes(mo, text)), 1)
        self.assertEqual(successor.crew_dep_conflict_since, self._utc(MONDAY, 11))
        self._train()
        self.assertEqual(len(self._notes(mo, text)), 1)
        successor.write(
            {"date_start": self._utc(MONDAY, 13), "date_finished": self._utc(MONDAY, 14)}
        )
        self._train()
        self.assertFalse(successor.crew_dep_conflict_since)

    def test_17_7_idempotent(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        self._train()
        write_date = stale.write_date
        self._train()
        self.assertEqual(len(self._batches()), 1)
        self.assertEqual(stale.write_date, write_date)
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)

    def test_17_8_same_hour_moves_nothing(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        with freeze_time("2026-10-05 08:20:00"):
            self.env["mrp.workcenter"]._cron_crew_train()
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        with freeze_time("2026-10-05 08:40:00"):
            self.env["mrp.workcenter"]._cron_crew_train()
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertEqual(len(self._batches()), 1)

    def test_17_9_locked_lane_skipped(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        self.Lock.with_user(self.mrp_user2)._crew_lane_take(self.wc_pg, 1)
        self._train()
        self.assertSlot(stale, MONDAY, 9, MONDAY, 10)

    def test_17_10_done_and_cancel_untouched(self):
        done = self._wo(self.wc_pg, MONDAY, 9)
        done.state = "done"
        cancel = self._wo(self.wc_pg, MONDAY, 9, 30, overlap=True)
        cancel.state = "cancel"
        self._train()
        self.assertSlot(done, MONDAY, 9, MONDAY, 10)
        self.assertSlot(cancel, MONDAY, 9, MONDAY, 10, minute=30, end_minute=30)

    def test_17_11_new_day_new_crew(self):
        self._roster(self.wc_pg, MONDAY, "08:00", self.emp3)
        self._roster(self.wc_pg, TUESDAY, "08:00", self.crew12)
        stale = self._wo(self.wc_pg, MONDAY, 9)
        self.assertEqual(stale.employee_assigned_ids, self.emp3)
        self._train(hour=17)
        self.assertSlot(stale, TUESDAY, 8, TUESDAY, 9)
        self.assertEqual(stale.crew_date, TUESDAY)
        self.assertEqual(stale.employee_assigned_ids, self.crew12)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestStretchAlarm(CrewLanesCommon):
    """18. Тревогата (Р37, M19): максимум 2 часа."""

    def setUp(self):
        super().setUp()
        self.wc_pg.write(
            {"crew_max_stretch_hours": 2.0, "crew_responsible_id": self.mrp_user.id}
        )

    def _running(self, finish_hour=9, day=MONDAY):
        wo = self._wo(self.wc_pg, day, finish_hour - 1)
        wo.state = "progress"
        wo.crew_planned_finish = self._utc(day, finish_hour)
        return wo

    def _activities(self, wo):
        return self.env["mail.activity"].search(
            [("res_model", "=", "mrp.production"), ("res_id", "=", wo.production_id.id)]
        )

    def _alerts(self, wo):
        return self._notes(wo.production_id, "past its planned end")

    def test_18_levels(self):
        wo = self._running()
        self.wc_pg._crew_train(self._utc(MONDAY, 10, 54))
        self.assertAlmostEqual(wo.crew_stretch_hours, 1.9, places=4)
        self.assertEqual((len(self._activities(wo)), wo.crew_stretch_alert_level), (0, 0))
        self.wc_pg._crew_train(self._utc(MONDAY, 11, 6))
        self.assertEqual(wo.crew_stretch_alert_level, 1)
        self.assertEqual(len(self._activities(wo)), 1)
        self.assertEqual(self._activities(wo).user_id, self.mrp_user)
        self.assertEqual(len(self._alerts(wo)), 1)
        self.assertTrue(wo.crew_is_overstretched)
        self.wc_pg._crew_train(self._utc(MONDAY, 11, 6))
        self.assertEqual((len(self._activities(wo)), len(self._alerts(wo))), (1, 1))
        # 09–12 + 13–13:54 = 3,9 ч (обядът не се брои).
        self.wc_pg._crew_train(self._utc(MONDAY, 13, 54))
        self.assertAlmostEqual(wo.crew_stretch_hours, 3.9, places=4)
        self.assertEqual(wo.crew_stretch_alert_level, 1)
        self.assertEqual(len(self._activities(wo)), 1)
        self.wc_pg._crew_train(self._utc(MONDAY, 14, 6))
        self.assertEqual(wo.crew_stretch_alert_level, 2)
        self.assertEqual((len(self._activities(wo)), len(self._alerts(wo))), (2, 2))

    def test_18_without_responsible_only_note(self):
        self.wc_pg.crew_responsible_id = False
        wo = self._running()
        self.wc_pg._crew_train(self._utc(MONDAY, 11, 6))
        self.assertEqual(wo.crew_stretch_alert_level, 1)
        self.assertFalse(self._activities(wo))
        self.assertEqual(len(self._alerts(wo)), 1)

    def test_18_max_zero_disables(self):
        self.wc_pg.crew_max_stretch_hours = 0.0
        wo = self._running()
        self.wc_pg._crew_train(self._utc(MONDAY, 16))
        self.assertEqual(wo.crew_stretch_alert_level, 0)
        self.assertFalse(self._alerts(wo))
        self.assertFalse(wo.crew_is_overstretched)

    def test_18_manual_replan_resets(self):
        wo = self._running()
        self.wc_pg._crew_train(self._utc(MONDAY, 11, 6))
        self.assertEqual(wo.crew_stretch_alert_level, 1)
        wo.write({"date_finished": self._utc(MONDAY, 15)})
        self.assertEqual(wo.crew_planned_finish, self._utc(MONDAY, 15))
        self.assertEqual(wo.crew_stretch_alert_level, 0)

    def test_18_night_not_counted(self):
        wo = self._running(finish_hour=16)
        self.wc_pg._crew_train(self._utc(TUESDAY, 9, 6))
        self.assertAlmostEqual(wo.crew_stretch_hours, 2.1, places=4)
        self.assertEqual(wo.crew_stretch_alert_level, 1)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLaneLock(CrewLanesCommon):
    """19. Ключалката и шината (Р38, M20)."""

    def test_19_1_second_gets_the_name(self):
        first = self.Lock.with_user(self.mrp_user).crew_lane_acquire(self.wc_pg.id, 1)
        self.assertTrue(first["ok"])
        second = self.Lock.with_user(self.mrp_user2).crew_lane_acquire(self.wc_pg.id, 1)
        self.assertFalse(second["ok"])
        self.assertEqual(second["user"], self.mrp_user.name)
        again = self.Lock.with_user(self.mrp_user).crew_lane_acquire(self.wc_pg.id, 1)
        self.assertTrue(again["ok"], "своята се подновява")

    def test_19_2_expires(self):
        self.Lock.with_user(self.mrp_user).crew_lane_acquire(self.wc_pg.id, 1)
        with freeze_time("2026-10-05 08:01:01"):
            second = self.Lock.with_user(self.mrp_user2).crew_lane_acquire(
                self.wc_pg.id, 1
            )
        self.assertTrue(second["ok"])

    def test_19_3_ping_renews_only_own(self):
        Lock = self.Lock
        Lock.with_user(self.mrp_user).crew_lane_acquire(self.wc_pg.id, 1)
        Lock.with_user(self.mrp_user2).crew_lane_acquire(self.wc_two.id, 1)
        with freeze_time("2026-10-05 08:00:30"):
            Lock.with_user(self.mrp_user).crew_lane_ping(self.wc_pg.id, 1)
        own = Lock.search([("user_id", "=", self.mrp_user.id)])
        other = Lock.search([("user_id", "=", self.mrp_user2.id)])
        self.assertEqual(own.expires_at, fields.Datetime.to_datetime("2026-10-05 08:01:30"))
        self.assertEqual(other.expires_at, fields.Datetime.to_datetime("2026-10-05 08:01:00"))
        self.assertTrue(self._bus("mrp_crew_lane/drag"))

    def test_19_4_release(self):
        self.Lock.with_user(self.mrp_user).crew_lane_acquire(self.wc_pg.id, 1)
        count = self.Lock.with_user(self.mrp_user).crew_lane_release(self.wc_pg.id, 1)
        self.assertEqual(count, 1)
        self.assertFalse(self.Lock.search([]))
        self.assertTrue(self._bus("mrp_crew_lane/released"))

    def test_19_5_payload_and_channel(self):
        wo = self._wo(self.wc_pg, TUESDAY, 9)
        self.Lock.with_user(self.mrp_user).crew_lane_acquire(
            self.wc_pg.id, 1, workorder_id=wo.id, tab="tab-1"
        )
        channel, payload = self._bus("mrp_crew_lane/locked")[-1]
        self.assertEqual(
            channel, [self.env.cr.dbname, "res.company", self.company.id, "mrp_crew_lane"]
        )
        self.assertEqual(
            (payload["workcenter_id"], payload["lane"], payload["workorder_id"]),
            (self.wc_pg.id, 1, wo.id),
        )
        self.assertEqual(
            (payload["user_id"], payload["user_name"], payload["tab"]),
            (self.mrp_user.id, self.mrp_user.name, "tab-1"),
        )

    def test_19_6_channel_only_for_the_group_and_companies(self):
        other_company = self.env["res.company"].create({"name": "Crew Other Co"})
        outsider = new_test_user(
            self.env,
            login="crew_lanes_outsider",
            email="crew_lanes_outsider@crew-test.invalid",
            groups="base.group_user",
            company_id=self.company.id,
            company_ids=[Command.set(self.company.ids)],
        )
        Websocket = self.env["ir.websocket"]
        channels = Websocket.with_user(self.mrp_user)._crew_lane_channels()
        self.assertEqual(channels, [(self.company, "mrp_crew_lane")])
        self.assertNotIn((other_company, "mrp_crew_lane"), channels)
        self.assertEqual(Websocket.with_user(outsider)._crew_lane_channels(), [])
        request = MagicMock()
        request.session.uid = self.mrp_user.id
        # В 18 и mail (гостът в add_guest_to_context) чете request: без
        # бисквитка гост няма, средата е тази на теста.
        request.cookies = {}
        request.env = self.env
        with patch("odoo.addons.bus.models.ir_websocket.request", request), patch(
            "odoo.addons.mail.models.discuss.mail_guest.request", request
        ):
            full = Websocket.with_user(self.mrp_user)._build_bus_channel_list(
                ["mrp_crew_lane"]
            )
        self.assertIn((self.company, "mrp_crew_lane"), full)
        self.assertNotIn("mrp_crew_lane", [c for c in full if isinstance(c, str)])


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLaneMigration(CrewLanesCommon):
    """20. Миграцията 19.0.1.5.0 (§9.5)."""

    def test_20_migration(self):
        running = self._wo(self.wc_pg, MONDAY, 9)
        running.state = "progress"
        self.assertFalse(running.crew_planned_finish)
        first = self._wo(self.wc_pg, TUESDAY, 9)
        second = self._wo(self.wc_pg, TUESDAY, 9, 30, overlap=True)
        cron = self.env.ref("mrp_workcenter_crew_roster.ir_cron_crew_train")
        cron.active = True
        report = self.WO._crew_migrate_1_5_0()
        self.assertEqual(running.crew_planned_finish, running.date_finished)
        self.assertEqual(report.get(self.wc_pg.id), 1)
        self.assertEqual((first.crew_lane, second.crew_lane), (1, 1))
        self.assertSlot(second, TUESDAY, 9, TUESDAY, 10, minute=30, end_minute=30)
        self.assertFalse(cron.active)

    def test_20_cron_installed_inactive(self):
        cron = self.env.ref("mrp_workcenter_crew_roster.ir_cron_crew_train")
        self.assertEqual((cron.interval_number, cron.interval_type), (1, "hours"))
        self.assertEqual(cron.code.strip(), "model._cron_crew_train()")


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLaneGantt(CrewLanesCommon):
    """22. M21 `get_gantt_data` и M22 проекцията на влака."""

    def _gantt(self, groupby):
        return self.WO.get_gantt_data(
            [("workcenter_id", "in", [self.wc_two.id])],
            groupby,
            {"date_start": {}, "date_finished": {}},
            start_date="2026-10-04 21:00:00",
            stop_date="2026-10-11 21:00:00",
            scale="week",
        )

    def test_22_1b_selected_centers_without_orders_are_shown(self):
        """Росен 12.10.2026: в „Планирай център“ се виждат всички избрани
        центрове, и тези без поръчки — празна група с писта 1."""
        self._wo(self.wc_two, TUESDAY, 9)
        data = self.WO.with_context(
            crew_workcenter_ids=[self.wc_pg.id, self.wc_two.id]
        ).get_gantt_data(
            [("workcenter_id", "in", [self.wc_pg.id, self.wc_two.id])],
            ["workcenter_id", "crew_lane"],
            {"date_start": {}, "date_finished": {}},
            start_date="2026-10-04 21:00:00",
            stop_date="2026-10-11 21:00:00",
            scale="week",
        )
        by_center = {group["workcenter_id"][0]: group for group in data["groups"]}
        self.assertEqual(set(by_center), {self.wc_pg.id, self.wc_two.id})
        empty = by_center[self.wc_pg.id]
        self.assertEqual((empty["crew_lane"], empty["id:array_agg"]), (1, []))
        self.assertIn(self.wc_pg.id, data["crew_lanes"])
        # Без избор (обикновеният Гант) — само центровете с поръчки.
        plain = self._gantt(["workcenter_id", "crew_lane"])
        self.assertEqual(
            {group["workcenter_id"][0] for group in plain["groups"]}, {self.wc_two.id}
        )

    def test_22_1_gantt_data(self):
        self._wo(self.wc_two, TUESDAY, 9)
        self.Lock.with_user(self.mrp_user)._crew_lane_take(self.wc_two, 2)
        data = self._gantt(["workcenter_id", "crew_lane"])
        self.assertEqual(data["crew_lanes"], {self.wc_two.id: 2})
        self.assertEqual(
            [(lock["lane"], lock["user_id"]) for lock in data["crew_locks"]],
            [(2, self.mrp_user.id)],
        )
        self.assertEqual(data["server_now"], "2026-10-05 08:00:00")
        plain = self._gantt(["workcenter_id"])
        self.assertNotIn("crew_lanes", plain)
        self.assertNotIn("server_now", plain)

    def test_22_2_preview_does_not_write(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        nxt = self._wo(self.wc_pg, MONDAY, 11, 30)
        workorders = stale | nxt
        write_dates = workorders.mapped("write_date")
        WorkOrder = type(self.env["mrp.workorder"])

        def forbidden(records, vals):
            raise AssertionError("the preview wrote %s" % vals)

        with patch.object(WorkOrder, "write", forbidden):
            preview = workorders.with_user(self.mrp_user).crew_train_preview()
        self.assertEqual(workorders.mapped("write_date"), write_dates)
        self.assertEqual(preview["server_now"], "2026-10-05 08:00:00")
        records = preview["records"]
        self.assertEqual(
            (records[stale.id]["date_start"], records[nxt.id]["date_start"]),
            ("2026-10-05 08:00:00", "2026-10-05 10:00:00"),
        )
        self.wc_pg._crew_train(fields.Datetime.now())
        for wo in workorders:
            self.assertEqual(
                (
                    fields.Datetime.to_string(wo.date_start),
                    fields.Datetime.to_string(wo.date_finished),
                ),
                (records[wo.id]["date_start"], records[wo.id]["date_finished"]),
            )
