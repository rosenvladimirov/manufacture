"""Залепването на първия вагон за влака (Росен 13.10.2026).

„Когато работните поръчки са отделени от влака, при изместване на който и
да е вагон винаги първият да се залепя за влака, за да може влакът да бута
вагоните.“ Решения от същия ден: при всяко ръчно местене (часовият влак е
без промяна); вагон, дръпнат напред с празнина пред него, се връща на
влака.

„Сега“ е понеделник 05.10.2026 11:00 местно време (като в test_lanes).
"""
from freezegun import freeze_time

from odoo.tests import tagged

from .common import MONDAY
from .test_lanes import FROZEN_NOW, TUESDAY, WEDNESDAY
from .test_lanes_bound import CrewBoundCommon


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestHeadSnap(CrewBoundCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        (cls.wc_pg | cls.wc_two | cls.wc_other).crew_snap_head = True

    def test_drop_pulls_the_detached_head_to_the_train(self):
        """Пистата почва във вторник — при пускане първият вагон отива на
        „сега“; следващите стоят (влакът ги бута, когато опрат)."""
        a = self._wo(self.wc_pg, TUESDAY, 8)
        b = self._wo(self.wc_pg, TUESDAY, 9)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        result = x.crew_drop(self.wc_pg.id, 1, after_workorder_id=b.id)
        self.assertSlot(a, MONDAY, 11, MONDAY, 12)
        self.assertSlot(b, TUESDAY, 9, TUESDAY, 10)
        self.assertSlot(x, TUESDAY, 10, TUESDAY, 11, second=1)
        reasons = {m["id"]: m["reason"] for m in result["moves"]}
        self.assertEqual(reasons, {x.id: "drop", a.id: "train"})

    def test_head_dragged_forward_returns_to_the_train(self):
        """Решение „Връща се на влака“: празнина в началото не остава."""
        a = self._wo(self.wc_pg, TUESDAY, 8)
        a.crew_drop(self.wc_pg.id, 1, date_start=self._utc(WEDNESDAY, 8))
        self.assertSlot(a, MONDAY, 11, MONDAY, 12)

    def test_head_attaches_after_the_started_wagon(self):
        """Влакът е краят на започнатата поръчка пред вагона."""
        started = self._wo(self.wc_pg, MONDAY, 10, minutes=120.0)
        started.state = "progress"
        a = self._wo(self.wc_pg, TUESDAY, 8)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        x.crew_drop(self.wc_pg.id, 1, after_workorder_id=a.id)
        self.assertSlot(started, MONDAY, 10, MONDAY, 12)
        # 12–13 е обедът: първият работен миг след влака е 13:00.
        self.assertSlot(a, MONDAY, 13, MONDAY, 14)

    def test_lane_left_behind_also_snaps(self):
        """Вагонът отива в друга писта — и в двете първият е на влака."""
        a = self._wo(self.wc_two, TUESDAY, 8)
        b = self._wo(self.wc_two, TUESDAY, 9)
        self.assertEqual((a.crew_lane, b.crew_lane), (1, 1))
        a.crew_drop(self.wc_two.id, 2, date_start=self._utc(WEDNESDAY, 8))
        self.assertEqual(a.crew_lane, 2)
        self.assertSlot(a, MONDAY, 11, MONDAY, 12)
        self.assertSlot(b, MONDAY, 11, MONDAY, 12)

    def test_bound_is_kept(self):
        """Границата на другия модул (напр. торбите не преди фолиото) важи."""
        a = self._wo(self.wc_pg, WEDNESDAY, 8)
        x = self._wo(self.wc_pg, WEDNESDAY, 12)
        with self._earliest({a: self._utc(TUESDAY, 8)}):
            x.crew_drop(self.wc_pg.id, 1, after_workorder_id=a.id)
        self.assertSlot(a, TUESDAY, 8, TUESDAY, 9)

    def test_switched_off_keeps_the_gap(self):
        self.wc_pg.crew_snap_head = False
        a = self._wo(self.wc_pg, TUESDAY, 8)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        x.crew_drop(self.wc_pg.id, 1, after_workorder_id=a.id)
        self.assertSlot(a, TUESDAY, 8, TUESDAY, 9)

    def test_write_outside_the_gantt_snaps(self):
        """Запис от формата: първият вагон, дръпнат напред, се връща."""
        a = self._wo(self.wc_pg, TUESDAY, 8)
        b = self._wo(self.wc_pg, WEDNESDAY, 12)
        a.write(
            {
                "date_start": self._utc(TUESDAY, 10),
                "date_finished": self._utc(TUESDAY, 11),
            }
        )
        self.assertSlot(a, MONDAY, 11, MONDAY, 12)
        self.assertSlot(b, WEDNESDAY, 12, WEDNESDAY, 13)

    def test_head_moved_behind_the_next_one(self):
        """Първият, преместен зад следващия: залепва се новият първи."""
        a = self._wo(self.wc_pg, TUESDAY, 8)
        b = self._wo(self.wc_pg, TUESDAY, 14)
        a.write(
            {
                "date_start": self._utc(WEDNESDAY, 8),
                "date_finished": self._utc(WEDNESDAY, 9),
            }
        )
        self.assertSlot(b, MONDAY, 11, MONDAY, 12)
        self.assertSlot(a, WEDNESDAY, 8, WEDNESDAY, 9)

    def test_create_with_dates_is_not_a_move(self):
        """Поръчка, създадена с дати (импорт), не се залепва."""
        a = self._wo(self.wc_pg, TUESDAY, 8)
        self.assertSlot(a, TUESDAY, 8, TUESDAY, 9)

    def test_undo_returns_the_head(self):
        """Залепването е в партидата на пускането — отмяната го връща."""
        a = self._wo(self.wc_pg, TUESDAY, 8)
        x = self._wo(self.wc_pg, WEDNESDAY, 8)
        result = x.crew_drop(self.wc_pg.id, 1, after_workorder_id=a.id)
        self.assertSlot(a, MONDAY, 11, MONDAY, 12)
        self.Batch.browse(result["batch_id"]).action_undo()
        self.assertSlot(a, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)
