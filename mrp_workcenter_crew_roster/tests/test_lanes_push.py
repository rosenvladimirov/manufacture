# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""19.0.1.5.3 — две поправки от 07.10 (Росен).

1. Влакът (M18) не спира минаването на първия валиден незапочнат вагон,
   ако по-нататък в пистата има заварено застъпване. Живият случай
   (тестовата, Екструдер 5, писта 1): започнати 140 и 154, незапочната 128,
   започната 176, незапочната 211 застъпва 176 — 211 трябва да отиде след
   176. Проекцията M22 показва същото, което влакът записва.
2. Р32 (изменено): запис ИЗВЪН нашия Гант (форма, стандартният Гант на EE,
   импорт, RPC) с нови дати, които опират в незапочнати поръчки в същата
   писта, ги избутва верижно (веригата на M17); започната в пътя → отказ;
   зависимост на друг център → отказ с обяснение, освен със съгласие в
   контекста (**19.0.1.5.5, Р33 изменено:** без отказ и без съгласие —
   зависимата не се мести, двете мигат); партида `write` за одит и
   отмяна; без рекурсия в собствените пътища на модула (двигател, влак,
   `crew_drop`, старт)."""
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import MONDAY
from .test_lanes import FROZEN_NOW, TUESDAY, WEDNESDAY, CrewLanesCommon

THURSDAY = MONDAY + timedelta(days=3)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestTrainLaterOverlap(CrewLanesCommon):
    """Поправка 1: заварено застъпване по-нататък в пистата."""

    def setUp(self):
        super().setUp()
        # „140“: започната, до вторник 09:00 (сега е понеделник 11:00).
        self.s140 = self._wo(self.wc_pg, MONDAY, 10, minutes=23 * 60, state="progress")
        # „128“: незапочната, валидна на мястото си.
        self.u128 = self._wo(self.wc_pg, WEDNESDAY, 8)
        # „176“: започната, сряда 10:00 – четвъртък 12:00.
        self.s176 = self._wo(
            self.wc_pg, WEDNESDAY, 10, minutes=26 * 60, state="progress"
        )
        # „211“: незапочната, ЗАСТЪПВА 176 (заварено, преди 1.5.0).
        self.u211 = self._wo(self.wc_pg, THURSDAY, 9, minutes=120, overlap=True)
        self.wagons = self.s140 | self.u128 | self.s176 | self.u211

    def test_r36_train_moves_a_later_overlap(self):
        self.wc_pg._crew_train(self._utc(MONDAY, 11))
        # 128 стои; 211 отива след края на 176 (12:00), през обяда.
        self.assertSlot(self.u128, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(self.u211, THURSDAY, 13, THURSDAY, 15)
        self.assertSlot(self.s176, WEDNESDAY, 10, THURSDAY, 12)
        batch = self.Batch.search([("source", "=", "train")])
        self.assertEqual(batch.line_ids.workorder_id, self.u211)

    def test_r36_preview_equals_the_record_after_a_later_overlap(self):
        preview = self.wagons.crew_train_preview()["records"]
        self.assertEqual(set(preview), {self.u211.id})
        self.wc_pg._crew_train(self._utc(MONDAY, 11))
        self.wagons.invalidate_recordset()
        self.assertEqual(
            (preview[self.u211.id]["date_start"], preview[self.u211.id]["date_finished"]),
            (
                fields.Datetime.to_string(self.u211.date_start),
                fields.Datetime.to_string(self.u211.date_finished),
            ),
        )
        # След влака проекцията не мести нищо (идемпотентност, П8).
        self.assertFalse(self.wagons.crew_train_preview()["records"])

    def test_r36_overlap_between_two_unstarted_later(self):
        """Застъпване между два незапочнати по-нататък — вторият се мести."""
        late = self._wo(self.wc_pg, THURSDAY, 16)
        later = self._wo(self.wc_pg, THURSDAY, 16, 30, overlap=True)
        self.wc_pg._crew_train(self._utc(MONDAY, 11))
        self.assertSlot(self.u128, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(late, THURSDAY, 16, THURSDAY, 17)
        # Четвъртък 17:00 е краят на деня — петък 08:00.
        self.assertSlot(later, THURSDAY + timedelta(days=1), 8, THURSDAY + timedelta(days=1), 9)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestWritePush(CrewLanesCommon):
    """Поправка 2: Р32 при запис извън нашия Гант."""

    def setUp(self):
        super().setUp()
        self.a = self._wo(self.wc_pg, WEDNESDAY, 8)
        self.b = self._wo(self.wc_pg, WEDNESDAY, 9)
        self.c = self._wo(self.wc_pg, WEDNESDAY, 13)
        self.x = self._wo(self.wc_pg, THURSDAY, 8)

    def _move_x(self, workorder=None, **context):
        (workorder or self.x).with_context(**context).write(
            {
                "date_start": self._utc(WEDNESDAY, 8),
                "date_finished": self._utc(WEDNESDAY, 9),
            }
        )

    @contextmanager
    def _spy_push(self):
        """Брои повикванията на избутването (без да го подменя)."""
        WorkOrder = type(self.env["mrp.workorder"])
        original = WorkOrder._crew_push_after_write
        calls = []

        def spy(records, old):
            calls.append(records.ids)
            return original(records, old)

        with patch.object(WorkOrder, "_crew_push_after_write", spy):
            yield calls

    def test_r32_write_pushes_the_chain(self):
        self._move_x()
        self.assertSlot(self.x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(self.a, WEDNESDAY, 9, WEDNESDAY, 10, second=1)
        self.assertSlot(self.b, WEDNESDAY, 10, WEDNESDAY, 11, second=1)
        # Дупката (11–13) спира веригата.
        self.assertSlot(self.c, WEDNESDAY, 13, WEDNESDAY, 14)

    def test_r32_write_batch_and_undo(self):
        self._move_x()
        batch = self.Batch.search([("source", "=", "write")])
        self.assertEqual(len(batch), 1)
        reasons = {line.workorder_id: line.reason for line in batch.line_ids}
        self.assertEqual(
            reasons, {self.x: "write", self.a: "chain", self.b: "chain"}
        )
        line_x = batch.line_ids.filtered(lambda line: line.workorder_id == self.x)
        self.assertEqual(line_x.old_date_start, self._utc(THURSDAY, 8))
        batch.action_undo()
        self.assertEqual(batch.state, "undone")
        self.assertSlot(self.x, THURSDAY, 8, THURSDAY, 9)
        self.assertSlot(self.a, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(self.b, WEDNESDAY, 9, WEDNESDAY, 10)

    def test_r32_write_into_started_refuses(self):
        self.b.state = "progress"
        with self.assertRaisesText(UserError, "started work order"):
            self._move_x()
        self.assertSlot(self.x, THURSDAY, 8, THURSDAY, 9)
        self.assertSlot(self.a, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertFalse(self.Batch.search([("source", "=", "write")]))

    def test_r32_dependency_on_other_center_blinks(self):
        """Р33 изменено (1.5.5): записът минава без съгласие и без отказ;
        зависимата на друг център не се мести; двете мигат, докато датите
        не се оправят."""
        mo = self._mo()
        first = self._wo(self.wc_pg, TUESDAY, 8, mo=mo, sequence=1)
        dependent = self._wo(self.wc_other, TUESDAY, 9, mo=mo, sequence=2)
        self.assertEqual(dependent.blocked_by_workorder_ids, first)
        x = self._wo(self.wc_pg, THURSDAY, 10)
        x.write({"date_start": self._utc(TUESDAY, 8), "date_finished": self._utc(TUESDAY, 9)})
        self.assertSlot(x, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(first, TUESDAY, 9, TUESDAY, 10, second=1)
        self.assertSlot(dependent, TUESDAY, 9, TUESDAY, 10)
        batch = self.Batch.search([("source", "=", "write")])
        self.assertEqual(batch.line_ids.workorder_id, x | first)
        self.assertTrue(first.crew_dep_conflict)
        self.assertTrue(dependent.crew_dep_conflict)
        self.assertFalse(x.crew_dep_conflict)
        # Оправяне: зависимата след края на предшественика — флагът изчезва.
        dependent.write(
            {"date_start": self._utc(TUESDAY, 10), "date_finished": self._utc(TUESDAY, 11)}
        )
        self.assertFalse(first.crew_dep_conflict)
        self.assertFalse(dependent.crew_dep_conflict)

    def test_r32_ee_gantt_reschedule_pushes(self):
        """Стандартният Гант на EE в 18: влаченето на пила е обикновен
        `write` на датите (web_gantt_reschedule в 18 е само за зависимости
        — посока forward/backward — и не носи датите)."""
        self.x.write(
            {
                "date_start": fields.Datetime.to_string(self._utc(WEDNESDAY, 8)),
                "date_finished": fields.Datetime.to_string(self._utc(WEDNESDAY, 9)),
            }
        )
        self.assertSlot(self.x, WEDNESDAY, 8, WEDNESDAY, 9)
        self.assertSlot(self.a, WEDNESDAY, 9, WEDNESDAY, 10, second=1)
        self.assertSlot(self.b, WEDNESDAY, 10, WEDNESDAY, 11, second=1)

    def test_r32_create_pushes(self):
        """Импорт/RPC: създаване с дати върху незапочната я избутва."""
        new = self._wo(self.wc_pg, WEDNESDAY, 8, 30)
        self.assertSlot(new, WEDNESDAY, 8, WEDNESDAY, 9, minute=30, end_minute=30)
        self.assertSlot(self.a, WEDNESDAY, 9, WEDNESDAY, 10, minute=30, end_minute=30, second=1)
        self.assertSlot(self.b, WEDNESDAY, 10, WEDNESDAY, 11, minute=30, end_minute=30, second=1)
        batch = self.Batch.search([("source", "=", "write")])
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch.line_ids.workorder_id, new | self.a | self.b)
        line = batch.line_ids.filtered(lambda line: line.workorder_id == new)
        self.assertFalse(line.old_date_start)

    def test_r32_own_paths_do_not_push(self):
        """Двигателят, влакът, `crew_drop` и стартът минават под
        `crew_lane_defer` — избутването не се вика в тях (без рекурсия)."""
        stale = self._wo(self.wc_pg, MONDAY, 8)
        stale2 = self._wo(self.wc_other, MONDAY - timedelta(days=3), 9)
        y = self._wo(self.wc_pg, MONDAY, 13)
        with self._spy_push() as calls:
            # Влакът.
            self.wc_pg._crew_train(self._utc(MONDAY, 11))
            self.assertSlot(stale, MONDAY, 11, MONDAY, 12)
            # Двигателят (Recompute).
            self.Batch._crew_run(
                {
                    "workcenter_ids": [self.wc_other.id],
                    "date_from": MONDAY,
                    "date_to": MONDAY + timedelta(days=14),
                    "only_stale": True,
                },
                "recompute",
            )
            self.assertSlot(stale2, MONDAY, 11, MONDAY, 12)
            # „Пусни тук“ с верига.
            result = self.x.crew_drop(self.wc_pg.id, 1, after_workorder_id=self.a.id)
            self.assertEqual(result["status"], "done")
            self.assertSlot(self.b, WEDNESDAY, 10, WEDNESDAY, 11, second=1)
            # Стартът, който бута незапочнатата в пистата.
            y.button_start(bypass=True)
            self.assertEqual(y.state, "progress")
            self.assertFalse(calls)
            # Обикновен запис извън Ганта — вика се (шпионинът работи).
            self._move_x(self.c)
            self.assertEqual(len(calls), 1)
