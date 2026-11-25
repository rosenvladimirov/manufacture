# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""19.0.1.5.2: находката от живия тест на 07.10 — чуждо ограничение
(„торбите не преди фолиото“) отказва записа на влака за един вагон.

1. Влакът ползва `_crew_replan_earliest()` (точката за разширение на M6)
   като долна граница на началото на незапочнат вагон — и часовата
   задача, и проекцията M22.
2. Отказ при запис на един вагон не пуска цялата писта: вагонът стои
   (неподвижна пречка), останалите се теглят.
3. Бележка до отговорника на центъра веднъж, докато отказът трае; без
   отговорник — само лог.
4. Проекцията M22 показва отказания вагон там, където е в базата.

Чуждото ограничение се симулира с patch на `write` на поръчката, който
вдига UserError при нови дати за конкретната поръчка (кодът на другия
модул не се чете — clean-room)."""
from contextlib import contextmanager
from unittest.mock import patch

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import MONDAY
from .test_lanes import FROZEN_NOW, CrewLanesCommon

REFUSAL = "is scheduled to start before the film is finished"
NOTE = "The train could not move"


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestTrainRefusal(CrewLanesCommon):
    """Влакът и отказът на чужд модул (19.0.1.5.2)."""

    def setUp(self):
        super().setUp()
        self.wc_pg.crew_responsible_id = self.mrp_user
        # Три остарели вагона в писта 1 (сега е понеделник 11:00).
        self.a = self._wo(self.wc_pg, MONDAY, 8)
        self.b = self._wo(self.wc_pg, MONDAY, 9)
        self.c = self._wo(self.wc_pg, MONDAY, 10)

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

    def _train(self, hour=11):
        self.wc_pg._crew_train(self._utc(MONDAY, hour))

    def _db_dates(self, workorders):
        workorders.invalidate_recordset()
        return {
            wo.id: (
                fields.Datetime.to_string(wo.date_start),
                fields.Datetime.to_string(wo.date_finished),
            )
            for wo in workorders
        }

    def test_r36_refused_wagon_stays_the_others_are_pulled(self):
        with self._refuse(self.b):
            self._train()
        self.assertSlot(self.a, MONDAY, 11, MONDAY, 12)
        self.assertSlot(self.b, MONDAY, 9, MONDAY, 10)
        # b е неподвижна пречка: c тръгва след края на a, през обяда.
        self.assertSlot(self.c, MONDAY, 13, MONDAY, 14)
        batch = self.Batch.search([("source", "=", "train")])
        self.assertEqual(batch.line_ids.workorder_id, self.a | self.c)
        self.assertEqual(self.b.crew_train_refused_since, self._utc(MONDAY, 11))
        self.assertFalse(any((self.a | self.c).mapped("crew_train_refused_since")))

    def test_r35_refusal_note_once_then_cleared(self):
        with self._refuse(self.b):
            self._train()
            notes = self._notes(self.b.production_id, NOTE)
            self.assertEqual(len(notes), 1)
            self.assertIn(REFUSAL, notes.body)
            self.assertEqual(notes.partner_ids, self.mrp_user.partner_id)
            self._train(hour=12)
            self._train(hour=13)
        self.assertEqual(len(self._notes(self.b.production_id, NOTE)), 1)
        self.assertEqual(self.b.crew_train_refused_since, self._utc(MONDAY, 11))
        # Причината е махната: вагонът се тегли, флагът се чисти.
        self._train(hour=14)
        self.assertSlot(self.b, MONDAY, 14, MONDAY, 15)
        self.assertFalse(self.b.crew_train_refused_since)
        self.assertEqual(len(self._notes(self.b.production_id, NOTE)), 1)

    def test_r35_refusal_without_responsible_only_logs(self):
        self.wc_pg.crew_responsible_id = False
        with self._refuse(self.b), self.assertLogs(
            "odoo.addons.mrp_workcenter_crew_roster.models.mrp_workcenter_lanes",
            level="WARNING",
        ) as logs:
            self._train()
        self.assertFalse(self._notes(self.b.production_id, NOTE))
        self.assertTrue(any(REFUSAL in line for line in logs.output))
        self.assertSlot(self.a, MONDAY, 11, MONDAY, 12)
        # Флагът се слага и без отговорник — по него стои проекцията.
        self.assertTrue(self.b.crew_train_refused_since)

    def test_r36_preview_equals_the_record_after_a_refusal(self):
        workorders = self.a | self.b | self.c
        with self._refuse(self.b):
            self._train()
            before = self._db_dates(workorders)
            preview = workorders.with_user(self.mrp_user).crew_train_preview()
            records = preview["records"]
            # Проекцията не мести отказания вагон; каквото показва = базата.
            self.assertNotIn(self.b.id, records)
            for wo in workorders:
                if wo.id in records:
                    self.assertEqual(
                        (records[wo.id]["date_start"], records[wo.id]["date_finished"]),
                        before[wo.id],
                        wo.display_name,
                    )
            # Второ пускане в същия час не мести нищо.
            self._train()
        self.assertEqual(self._db_dates(workorders), before)

    def test_r36_train_respects_replan_earliest(self):
        """Точката за разширение на M6 е долна граница и във влака: a не
        тръгва преди 14:00, b и c вървят след него (редът се пази)."""
        WorkOrder = type(self.env["mrp.workorder"])
        earliest = self._utc(MONDAY, 14)
        target = self.a

        def replan_earliest(record, params=None):
            self.assertTrue(params and "scope" in params)
            return earliest if record == target else False

        workorders = self.a | self.b | self.c
        with patch.object(WorkOrder, "_crew_replan_earliest", replan_earliest):
            preview = workorders.with_user(self.mrp_user).crew_train_preview()
            self.wc_pg._crew_train(fields.Datetime.now())
        self.assertSlot(self.a, MONDAY, 14, MONDAY, 15)
        self.assertSlot(self.b, MONDAY, 15, MONDAY, 16, second=1)
        self.assertSlot(self.c, MONDAY, 16, MONDAY, 17, second=1)
        records = preview["records"]
        dates = self._db_dates(workorders)
        for wo in workorders:
            self.assertEqual(
                (records[wo.id]["date_start"], records[wo.id]["date_finished"]),
                dates[wo.id],
                wo.display_name,
            )
