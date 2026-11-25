# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""19.0.1.5.4 — две поправки от 07.10 (Росен).

1. M17 (`crew_drop`) и Р32 при запис спазват границата
   `_crew_replan_earliest()` (точката за разширение на M6 и влака):
   избутаните вагони на веригата и зависимите по Р33 не започват преди нея.
   При пускане X отива на мястото на стрелката, а ако то е преди границата —
   на границата (с бележка). При пряк запис датите на X са на човека: не се
   местят, отказът е на другия модул.
2. „Пускането на стрелката разтваря място и вмъква поръчката вътре“:
   проекцията на влака в M17 закотвя отказаните вагони
   (`crew_train_refused_since`) само ПРЕДИ мястото — пускането не пада
   заради тях. Отказаните след мястото се избутват като всички; ако другият
   модул откаже записа — ясен отказ, който назовава вагона и причината.

Границата и чуждият отказ се симулират с patch (кодът на другия модул не
се чете — clean-room), както в test_lanes_train_refusal.py."""
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import MONDAY
from .test_lanes import FROZEN_NOW, TUESDAY, WEDNESDAY, CrewLanesCommon

THURSDAY = MONDAY + timedelta(days=3)
REFUSAL = "is scheduled to start before the film is finished"


class CrewBoundCommon(CrewLanesCommon):
    @contextmanager
    def _earliest(self, bounds):
        """Точката за разширение: {поръчка: най-ранно начало}."""
        WorkOrder = type(self.env["mrp.workorder"])
        by_id = {wo.id: moment for wo, moment in bounds.items()}

        def replan_earliest(record, params=None):
            self.assertTrue(params and "scope" in params)
            return by_id.get(record.id, False)

        with patch.object(WorkOrder, "_crew_replan_earliest", replan_earliest):
            yield

    @contextmanager
    def _refuse(self, target):
        """Чуждото ограничение: нови дати на `target` → UserError."""
        WorkOrder = type(self.env["mrp.workorder"])
        original = WorkOrder.write

        def guarded(records, vals):
            if "date_start" in vals and target.id in records.ids:
                raise UserError("Operation %s %s" % (target.display_name, REFUSAL))
            return original(records, vals)

        with patch.object(WorkOrder, "write", guarded):
            yield


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestDropBound(CrewBoundCommon):
    """Поправка 1: границата в M17 и в Р32 при запис."""

    def test_r32_drop_chain_respects_earliest(self):
        a = self._wo(self.wc_pg, TUESDAY, 8)
        b = self._wo(self.wc_pg, TUESDAY, 9)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        with self._earliest({b: self._utc(TUESDAY, 14)}):
            result = x.crew_drop(self.wc_pg.id, 1, after_workorder_id=a.id)
        self.assertEqual(result["status"], "done")
        self.assertSlot(x, TUESDAY, 9, TUESDAY, 10, second=1)
        # b не тръгва в 10:00 (краят на X), а на границата си. От 1.5.5
        # (находка 6ж) го мести още проекцията на влака — b е след валидния
        # a, но преди границата си; веригата не стига до него.
        self.assertSlot(b, TUESDAY, 14, TUESDAY, 15)
        reasons = {m["id"]: m["reason"] for m in result["moves"]}
        self.assertEqual(reasons, {x.id: "drop", b.id: "train"})

    def test_r33_write_dependents_respect_earliest(self):
        """Р33 при запис: зависимата не тръгва преди границата си. От
        1.5.5 (Р33 изменено) се избутва само зависима на СЪЩИЯ център —
        тук в другата писта; пистата на X е изрично подадена, за да не я
        „поправи“ M14.3. (При пускане зависимите са в пистите на проекцията
        на влака, която вече спазва границата.)"""
        mo = self._mo()
        first = self._wo(self.wc_two, TUESDAY, 8, mo=mo, sequence=1)
        dependent = self._wo(self.wc_two, TUESDAY, 9, mo=mo, sequence=2, crew_lane=2)
        self.assertEqual(dependent.blocked_by_workorder_ids, first)
        x = self._wo(self.wc_two, THURSDAY, 10)
        with self._earliest({dependent: self._utc(TUESDAY, 14)}):
            x.write(
                {
                    "date_start": self._utc(TUESDAY, 8),
                    "date_finished": self._utc(TUESDAY, 9),
                    "crew_lane": 1,
                }
            )
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(first, TUESDAY, 9, TUESDAY, 10, second=1)
        # Не в 10:00 (краят на first), а на границата.
        self.assertSlot(dependent, TUESDAY, 14, TUESDAY, 15)
        batch = self.Batch.search([("source", "=", "write")])
        line = batch.line_ids.filtered(lambda line: line.workorder_id == dependent)
        self.assertEqual(line.reason, "dependency")

    def test_r32_drop_before_earliest_goes_to_the_bound(self):
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        with self._earliest({x: self._utc(TUESDAY, 14)}):
            result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 9))
        self.assertEqual(result["status"], "done")
        self.assertSlot(x, TUESDAY, 14, TUESDAY, 15)
        # Отговорът го казва: бележка и ходът на X.
        self.assertTrue(
            any(x.display_name in note and "cannot start before" in note
                for note in result["notes"]),
            result["notes"],
        )
        move = next(m for m in result["moves"] if m["id"] == x.id)
        self.assertEqual(move["reason"], "drop")

    def test_r32_drop_after_the_bound_stays_at_the_arrow(self):
        """Мястото на стрелката е след границата — X е точно там."""
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        with self._earliest({x: self._utc(TUESDAY, 9)}):
            result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 10))
        self.assertSlot(x, TUESDAY, 10, TUESDAY, 11)
        self.assertFalse(
            any("cannot start before" in note for note in result["notes"])
        )

    def test_r32_write_chain_respects_earliest(self):
        a = self._wo(self.wc_pg, WEDNESDAY, 8)
        b = self._wo(self.wc_pg, WEDNESDAY, 9)
        c = self._wo(self.wc_pg, WEDNESDAY, 13)
        x = self._wo(self.wc_pg, THURSDAY, 8)
        with self._earliest({b: self._utc(WEDNESDAY, 14)}):
            x.write(
                {
                    "date_start": self._utc(WEDNESDAY, 8),
                    "date_finished": self._utc(WEDNESDAY, 9),
                }
            )
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(a, WEDNESDAY, 9, WEDNESDAY, 10, second=1)
        # b — на границата; c е след него, редът се пази.
        self.assertSlot(b, WEDNESDAY, 14, WEDNESDAY, 15)
        self.assertSlot(c, WEDNESDAY, 15, WEDNESDAY, 16, second=1)
        batch = self.Batch.search([("source", "=", "write")])
        self.assertEqual(batch.line_ids.workorder_id, x | a | b | c)

    def test_r32_write_keeps_x_before_its_earliest(self):
        """Пряк запис: датите на X са на човека — не се местят тихо."""
        a = self._wo(self.wc_pg, WEDNESDAY, 8)
        x = self._wo(self.wc_pg, WEDNESDAY, 13)
        with self._earliest({x: self._utc(WEDNESDAY, 10)}):
            x.write(
                {
                    "date_start": self._utc(WEDNESDAY, 8),
                    "date_finished": self._utc(WEDNESDAY, 9),
                }
            )
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(a, WEDNESDAY, 9, WEDNESDAY, 10, second=1)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestDropRefusedWagons(CrewBoundCommon):
    """Поправка 2: отказаните вагони и мястото на вмъкване."""

    def test_r36_refused_wagon_before_the_place_does_not_fail_the_drop(self):
        # Три остарели вагона; влакът не успява да мести b (чужд отказ).
        a = self._wo(self.wc_pg, MONDAY, 8)
        b = self._wo(self.wc_pg, MONDAY, 9)
        c = self._wo(self.wc_pg, MONDAY, 10)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        with self._refuse(b):
            self.wc_pg._crew_train(self._utc(MONDAY, 11))
            self.assertTrue(b.crew_train_refused_since)
            result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8))
        self.assertEqual(result["status"], "done")
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9)
        # b стои — проекцията не се опитва да го мести.
        self.assertSlot(b, MONDAY, 9, MONDAY, 10)
        self.assertSlot(a, MONDAY, 11, MONDAY, 12)
        self.assertSlot(c, MONDAY, 13, MONDAY, 14)
        self.assertNotIn(b.id, {m["id"] for m in result["moves"]})

    def _refused_after(self):
        b = self._wo(self.wc_pg, TUESDAY, 9)
        b.crew_train_refused_since = self._utc(MONDAY, 11)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        return b, x

    def test_r32_refused_wagon_after_the_place_is_pushed(self):
        b, x = self._refused_after()
        result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8, 30))
        self.assertEqual(result["status"], "done")
        # Стрелката разтваря място: X е точно там, b — след края му.
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9, minute=30, end_minute=30)
        self.assertSlot(b, TUESDAY, 9, TUESDAY, 10, minute=30, end_minute=30, second=1)
        reasons = {m["id"]: m["reason"] for m in result["moves"]}
        self.assertEqual(reasons[b.id], "chain")

    def test_r32_refused_wagon_after_the_place_refuses_the_drop_by_name(self):
        b, x = self._refused_after()
        with self._refuse(b), self.assertRaisesText(
            UserError, "Moving %s was refused" % b.display_name
        ) as catcher:
            x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8, 30))
        self.assertIn(REFUSAL, str(catcher.exception))
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(b, TUESDAY, 9, TUESDAY, 10)
        self.assertFalse(self.Batch.search([("source", "=", "drop")]))

    def test_r32_write_push_refused_by_name(self):
        """Р32 при запис: отказ при избутването на вагон → ясен отказ."""
        b, x = self._refused_after()
        with self._refuse(b), self.assertRaisesText(
            UserError, "Moving %s was refused" % b.display_name
        ):
            x.write(
                {
                    "date_start": self._utc(TUESDAY, 8, 30),
                    "date_finished": self._utc(TUESDAY, 9, 30),
                }
            )
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(b, TUESDAY, 9, TUESDAY, 10)
