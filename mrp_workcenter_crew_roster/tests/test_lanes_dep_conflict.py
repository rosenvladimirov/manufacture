# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""19.0.1.5.5 — две промени от 07.10 (Росен).

1. Находка 6ж (TECH_DESIGN §9.7, риск 13(в)): влакът спираше минаването на
   първия валиден вагон, ако нататък пистата е „чиста“ (`clean_from`), без
   да гледа границата `_crew_replan_earliest` на следващите. Вагон след
   валиден участък, който е ПРЕДИ границата си, оставаше там. Сега
   „чисто“ значи и „никой вагон нататък не е преди границата си“ — влакът,
   проекцията M22 и проекцията в M17 го местят на границата.
2. Р33 изменено: „Свързаните поръчки ги освободи да се местят, но тези
   които са свързани да почнат да мигат“. Зависимост на друг център не
   спира местенето (без питане и без отказ) и не се избутва; ако
   наследникът почва преди края на предшественика — И ДВЕТЕ са с
   `crew_dep_conflict` (мигат в Ганта), докато датите не се оправят.

Границата се симулира с patch (кодът на другия модул не се чете —
clean-room), както в test_lanes_bound.py."""
from datetime import timedelta

from freezegun import freeze_time

from odoo import fields
from odoo.tests import tagged

from .common import MONDAY
from .test_lanes import FROZEN_NOW, TUESDAY, WEDNESDAY
from .test_lanes_bound import CrewBoundCommon


def _s(value):
    return fields.Datetime.to_string(value)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestTrainEarliestAfterValid(CrewBoundCommon):
    """Находка 6ж: вагон след валиден участък, преди границата си."""

    def setUp(self):
        super().setUp()
        # a е валиден на мястото си; b е след него, без застъпване, но
        # границата му (напр. краят на фолиото) е вторник 14:00.
        self.a = self._wo(self.wc_pg, TUESDAY, 8)
        self.b = self._wo(self.wc_pg, TUESDAY, 9)
        self.bounds = {self.b: self._utc(TUESDAY, 14)}

    def test_r36_train_moves_a_wagon_before_its_earliest_after_a_valid_one(self):
        with self._earliest(self.bounds):
            self.wc_pg._crew_train(self._utc(MONDAY, 11))
        self.assertSlot(self.a, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(self.b, TUESDAY, 14, TUESDAY, 15)
        batch = self.Batch.search([("source", "=", "train")])
        self.assertEqual(batch.line_ids.workorder_id, self.b)

    def test_r36_preview_equals_the_record_before_the_earliest(self):
        with self._earliest(self.bounds):
            preview = (self.a | self.b).crew_train_preview()["records"]
            self.assertNotIn(self.a.id, preview)
            self.assertEqual(
                (preview[self.b.id]["date_start"], preview[self.b.id]["date_finished"]),
                (_s(self._utc(TUESDAY, 14)), _s(self._utc(TUESDAY, 15))),
            )
            # Часовата задача към същото „сега“ записва точно това.
            self.wc_pg._crew_train(self._utc(MONDAY, 11))
        self.assertEqual(
            (_s(self.b.date_start), _s(self.b.date_finished)),
            (preview[self.b.id]["date_start"], preview[self.b.id]["date_finished"]),
        )

    def test_r32_drop_projection_moves_a_wagon_before_its_earliest(self):
        """M17 гледа пистата през същата проекция: X се пуска далеч след b,
        а b пак отива на границата си (ход `train` в партидата на
        пускането)."""
        x = self._wo(self.wc_pg, WEDNESDAY + timedelta(days=1), 8)
        with self._earliest(self.bounds):
            result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(WEDNESDAY, 8))
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(self.a, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(self.b, TUESDAY, 14, TUESDAY, 15)
        reasons = {m["id"]: m["reason"] for m in result["moves"]}
        self.assertEqual(reasons, {x.id: "drop", self.b.id: "train"})


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestDependencyConflict(CrewBoundCommon):
    """Р33 изменено: конфликтът по зависимост мига, нищо не се отказва."""

    def test_r33_drop_before_the_predecessor_on_other_center_blinks(self):
        mo = self._mo()
        pred = self._wo(self.wc_other, TUESDAY, 10, mo=mo, sequence=1)
        x = self._wo(self.wc_pg, WEDNESDAY, 8, mo=mo, sequence=2)
        self.assertEqual(x.blocked_by_workorder_ids, pred)
        result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 8))
        self.assertEqual(result["status"], "done")
        # X е на стрелката — не е дръпнат след предшественика.
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(pred, TUESDAY, 10, TUESDAY, 11)
        self.assertTrue(x.crew_dep_conflict)
        self.assertTrue(pred.crew_dep_conflict)
        self.assertTrue(
            any(pred.display_name in note and x.display_name in note
                for note in result["notes"]),
            result["notes"],
        )
        # Пускане след края на предшественика — конфликтът изчезва.
        x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(TUESDAY, 11))
        self.assertSlot(x, TUESDAY, 11, TUESDAY, 12)
        self.assertFalse(x.crew_dep_conflict)
        self.assertFalse(pred.crew_dep_conflict)

    def test_r33_direct_write_into_a_dependency_blinks_without_error(self):
        mo = self._mo()
        x = self._wo(self.wc_pg, TUESDAY, 8, mo=mo, sequence=1)
        succ = self._wo(self.wc_other, TUESDAY, 9, mo=mo, sequence=2)
        self.assertEqual(succ.blocked_by_workorder_ids, x)
        self.assertFalse(x.crew_dep_conflict or succ.crew_dep_conflict)
        x.write({"date_start": self._utc(TUESDAY, 9), "date_finished": self._utc(TUESDAY, 10)})
        self.assertSlot(succ, TUESDAY, 9, TUESDAY, 10)
        self.assertTrue(x.crew_dep_conflict)
        self.assertTrue(succ.crew_dep_conflict)
        x.write({"date_start": self._utc(TUESDAY, 8), "date_finished": self._utc(TUESDAY, 9)})
        self.assertFalse(x.crew_dep_conflict)
        self.assertFalse(succ.crew_dep_conflict)

    def test_r33_flag_counts_open_dependencies_in_whole_seconds(self):
        mo = self._mo()
        pred = self._wo(self.wc_other, TUESDAY, 8, mo=mo, sequence=1)
        succ = self._wo(self.wc_pg, TUESDAY, 9, mo=mo, sequence=2)
        # Край с микросекунда (ход през полунощ, Н8) не е конфликт.
        pred.with_context(crew_lane_defer=True).write(
            {"date_finished": self._utc(TUESDAY, 9).replace(microsecond=1)}
        )
        self.assertFalse(pred.crew_dep_conflict or succ.crew_dep_conflict)
        pred.with_context(crew_lane_defer=True).write(
            {"date_finished": self._utc(TUESDAY, 9, 30)}
        )
        self.assertTrue(pred.crew_dep_conflict and succ.crew_dep_conflict)
        # Приключен/отменен предшественик не е конфликт.
        pred.state = "done"
        self.assertFalse(pred.crew_dep_conflict or succ.crew_dep_conflict)

    def test_r35_train_conflict_blinks_on_both_sides(self):
        """Р35: влакът не мести зависимата на друг център (както досега),
        но вече и двете мигат — по проекцията преди хода и по полето след
        него."""
        mo = self._mo()
        stale = self._wo(self.wc_pg, MONDAY, 9, mo=mo, sequence=1)
        successor = self._wo(self.wc_other, MONDAY, 11, 30, mo=mo, sequence=2)
        self.assertFalse(stale.crew_dep_conflict or successor.crew_dep_conflict)
        preview = (stale | successor).crew_train_preview()["records"]
        self.assertTrue(preview[stale.id]["dep_alert"])
        self.assertTrue(preview[successor.id]["dep_alert"])
        self.wc_pg._crew_train(self._utc(MONDAY, 11))
        self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
        self.assertSlot(successor, MONDAY, 11, MONDAY, 12, minute=30, end_minute=30)
        self.assertTrue(stale.crew_dep_conflict)
        self.assertTrue(successor.crew_dep_conflict)
