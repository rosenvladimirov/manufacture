# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Стъпка 6б.3: допълнителни тестове към §9.8, които пазят правилата на
пистите по пътищата, където изборът на слот е „верен по построение“ и
затова крайната проверка M15 иначе не се упражнява (Р30 при двигателя,
влака и пускането — подправен ход), изтеклата ключалка (Р38) и вторият
пуск на часовата задача (Р36)."""
from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import MONDAY
from .test_lanes import FROZEN_NOW, TUESDAY, WEDNESDAY, FRIDAY, CrewLanesCommon


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLaneInvariantPaths(CrewLanesCommon):
    """Р30: M15 върви накрая по всеки път, който пише под `crew_lane_defer`
    (двигателят M6, влакът M18, пускането M17 — П17). Слотът се подправя,
    за да стане застъпване; проверката трябва да го хване и да върне
    записа."""

    def test_30_engine_forged_slot_fails(self):
        busy = self._wo(self.wc_pg, MONDAY, 13)
        stale = self._wo(self.wc_pg, FRIDAY, 9)
        Workcenter = type(self.env["mrp.workcenter"])
        forged = (1, self._utc(MONDAY, 13, 30), self._utc(MONDAY, 14, 30))
        with patch.object(
            Workcenter, "_crew_first_slot_lanes", lambda self, *args, **kwargs: forged
        ):
            batch = self.Batch._crew_run(
                {
                    "workcenter_ids": [self.wc_pg.id],
                    "date_from": MONDAY,
                    "date_to": MONDAY + timedelta(days=14),
                    "only_stale": True,
                },
                "recompute",
            )
        line = batch.line_ids.filtered(lambda line: line.workorder_id == stale)
        self.assertEqual(line.result, "failed")
        self.assertIn("never overlap", line.message)
        self.assertNotEqual(stale.date_start, self._utc(MONDAY, 13, 30))
        self.assertSlot(busy, MONDAY, 13, MONDAY, 14)

    def test_30_train_forged_walk_skips_lane(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        busy = self._wo(self.wc_pg, MONDAY, 13)
        Workcenter = type(self.env["mrp.workcenter"])
        forged = (self._utc(MONDAY, 13, 30), self._utc(MONDAY, 14, 30))
        with patch.object(Workcenter, "_crew_walk", lambda self, *args, **kwargs: forged):
            self.wc_pg._crew_train(self._utc(MONDAY, 11))
        # Пистата е пропусната (savepoint): нищо не е записано.
        self.assertSlot(stale, MONDAY, 9, MONDAY, 10)
        self.assertSlot(busy, MONDAY, 13, MONDAY, 14)
        self.assertFalse(self.Batch.search([("source", "=", "train")]))

    def test_30_drop_forged_move_rolls_back(self):
        """П17: M17 пише под `crew_lane_defer`; ход, който застъпва вагон,
        гърми в крайната M15 и връща всичко."""
        a = self._wo(self.wc_pg, TUESDAY, 9)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        WorkOrder = type(self.env["mrp.workorder"])
        original = WorkOrder._crew_drop_plan

        def forged_plan(records, *args, **kwargs):
            plan = original(records, *args, **kwargs)
            for move in plan["moves"]:
                if move["workorder"] == x:
                    move["date_start"] = self._utc(TUESDAY, 9, 30)
                    move["date_finished"] = self._utc(TUESDAY, 10, 30)
            return plan

        with patch.object(WorkOrder, "_crew_drop_plan", forged_plan):
            with self.assertRaisesText(ValidationError, "never overlap"):
                x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 13))
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(a, TUESDAY, 9, TUESDAY, 10)
        self.assertFalse(self.Batch.search([("source", "=", "drop")]))


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestLaneLockExpiry(CrewLanesCommon):
    """Р38: ключалката изтича след 1 минута — изтеклата не спира нито
    пускането (M17), нито влачене под флага (M16), нито влака (M18)."""

    def test_38_expired_lock_does_not_block(self):
        stale = self._wo(self.wc_pg, MONDAY, 9)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        self.Lock.with_user(self.mrp_user2)._crew_lane_take(self.wc_pg, 1)
        with freeze_time("2026-10-05 08:01:01"):
            self.assertFalse(self.Lock._crew_lane_locked(self.wc_pg, 1))
            self.wc_pg._crew_train(self._utc(MONDAY, 11))
            self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
            x.with_context(crew_gantt_drag=True).write({"name": "Crew dragged"})
            x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8))
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestTrainCronIdempotent(CrewLanesCommon):
    """Р36: вторият пуск на часовата задача в същия час не пише нищо — нито
    дати, нито партида, нито съобщение по шината, нито бележка."""

    def test_36_second_cron_run_does_nothing(self):
        mo = self._mo()
        stale = self._wo(self.wc_pg, MONDAY, 9, mo=mo, sequence=1)
        successor = self._wo(self.wc_other, MONDAY, 11, 30, mo=mo, sequence=2)
        Workcenter = self.env["mrp.workcenter"]

        def state():
            # Само следите на този тест: в базата може да има и други центрове.
            changed = [
                payload
                for _channel, payload in self._bus("mrp_crew_lane/changed")
                if stale.id in payload["workorder_ids"]
            ]
            return (
                stale.write_date,
                successor.write_date,
                len(changed),
                len(self._notes(mo, "The train did not move it")),
                self.Batch.search_count(
                    [("source", "=", "train"), ("workcenter_ids", "in", self.wc_pg.ids)]
                ),
            )

        with freeze_time("2026-10-05 08:20:00"):
            Workcenter._cron_crew_train()
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        first = state()
        self.assertEqual(first[2:], (1, 1, 1))
        with freeze_time("2026-10-05 08:50:00"):
            Workcenter._cron_crew_train()
        self.assertEqual(state(), first)
        self.assertSlot(successor, MONDAY, 11, MONDAY, 12, minute=30, end_minute=30)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestTrainDependencyNoteOnce(CrewLanesCommon):
    """Р35 + Р37 (без повторно съобщение): докато конфликтът със зависимата
    на друг център трае, следващите часове на влака я бутат пак, но
    бележката е една и `crew_dep_conflict_since` пази първия час."""

    def test_35_note_once_while_conflict_lasts(self):
        mo = self._mo()
        stale = self._wo(self.wc_pg, MONDAY, 9, mo=mo, sequence=1)
        successor = self._wo(self.wc_other, MONDAY, 11, 30, mo=mo, sequence=2)
        text = "The train did not move it"
        self.wc_pg._crew_train(self._utc(MONDAY, 11))
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertEqual(len(self._notes(mo, text)), 1)
        # Следващият час: незапочнатата пак е в миналото и влакът я бута на
        # 13–14 (след обяда); зависимата (11:30) още е застъпена.
        self.wc_pg._crew_train(self._utc(MONDAY, 13))
        self.assertSlot(stale, MONDAY, 13, MONDAY, 14)
        self.assertSlot(successor, MONDAY, 11, MONDAY, 12, minute=30, end_minute=30)
        self.assertEqual(len(self._notes(mo, text)), 1)
        self.assertEqual(successor.crew_dep_conflict_since, self._utc(MONDAY, 11))
