# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Стъпка 6б.4: тестовете на петте находки от двете обратни проверки на
пистите (07.10.2026). Всеки тест падаше на кода при 19.0.1.5.0 преди
поправката и пази правилото, което находката сочи:

1. Р33 — съгласието с верния токен прилага местенето, макар часовникът да
   е минал между двете повиквания (планът зависи от „сега“). **19.0.1.5.5
   (Р33 изменено, 07.10):** съгласието отпадна — зависимата на друг център
   на избутан вагон не се мести и не иска питане, а двете мигат.
2. Р38 — пистите, над които е минал влаченият вагон, не остават заключени:
   ping-ът пуска предишната цел, а пускането (M17) — всички ключалки на
   влачената поръчка.
3. Р38 — ping-ът казва какво наистина държи (`source_locked`,
   `target_locked`) и праща своето изтичане, не чуждото.
4. Р29 / M14.4 — стартът търси писта без ЗАПОЧНАТИ: незапочнатите в нея се
   избутват, вместо започнатата да застъпи друга започната.
5. Р37 / Р34 — късният старт пази дължината: планираният край е началото +
   продължителността по календара, не „сега“ или стария край.
"""
from freezegun import freeze_time

from odoo.tests import tagged

from .common import MONDAY
from .test_lanes import FROZEN_NOW, TUESDAY, WEDNESDAY, CrewLanesCommon


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReviewChainDependency(CrewLanesCommon):
    """Находка 1 (Р33), след изменението от 07.10 (19.0.1.5.5): без токен
    и без съгласие — избутаният вагон не бута зависимата си на друг
    център, а двете мигат."""

    def _setup_push(self):
        """Сега = 13:00 местно. X (30 мин) се пуска от 12:50, т.е. от сега:
        13:00–13:30; W1 (13:20, 30 мин) се избутва на 13:30–14:00; N1 —
        зависимата на W1 на друг център (13:50) — остава."""
        mo = self._mo()
        w1 = self._wo(self.wc_pg, MONDAY, 13, 20, minutes=30, mo=mo, sequence=1)
        n1 = self._wo(self.wc_other, MONDAY, 13, 50, mo=mo, sequence=2)
        self.assertEqual(n1.blocked_by_workorder_ids, w1)
        x = self._wo(self.wc_pg, TUESDAY, 9, minutes=30)
        return w1, n1, x

    def test_r33_chain_dependency_is_not_pushed_and_blinks(self):
        with freeze_time("2026-10-05 10:00:00"):
            w1, n1, x = self._setup_push()
            result = x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(MONDAY, 12, 50))
        self.assertEqual(result["status"], "done")
        self.assertSlot(x, MONDAY, 13, MONDAY, 13, end_minute=30)
        self.assertSlot(w1, MONDAY, 13, MONDAY, 14, minute=30, second=1)
        self.assertSlot(n1, MONDAY, 13, MONDAY, 14, minute=50, end_minute=50)
        reasons = {move["id"]: move["reason"] for move in result["moves"]}
        self.assertEqual(reasons, {x.id: "drop", w1.id: "chain"})
        self.assertTrue(w1.crew_dep_conflict)
        self.assertTrue(n1.crew_dep_conflict)
        self.assertFalse(x.crew_dep_conflict)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReviewPassedLanes(CrewLanesCommon):
    """Находка 2 (Р38): пистите, над които е минал вагонът."""

    def _held(self, user):
        return {
            (lock.workcenter_id, lock.lane)
            for lock in self.Lock.sudo().search([("user_id", "=", user.id)])
        }

    def test_r38_ping_releases_the_previous_target(self):
        x = self._wo(self.wc_two, TUESDAY, 9)
        self.assertEqual(x.crew_lane, 1)
        Lock = self.Lock.with_user(self.mrp_user)
        Lock.crew_lane_acquire(self.wc_two.id, 1, workorder_id=x.id, tab="t1")
        Lock.crew_lane_ping(
            self.wc_two.id, 1, workorder_id=x.id, target_workcenter_id=self.wc_two.id,
            target_lane=2, tab="t1",
        )
        self.assertEqual(self._held(self.mrp_user), {(self.wc_two, 1), (self.wc_two, 2)})
        Lock.crew_lane_ping(
            self.wc_two.id, 1, workorder_id=x.id, target_workcenter_id=self.wc_other.id,
            target_lane=1, tab="t1",
        )
        self.assertEqual(self._held(self.mrp_user), {(self.wc_two, 1), (self.wc_other, 1)})
        released = [p for _c, p in self._bus("mrp_crew_lane/released")]
        self.assertIn((self.wc_two.id, 2), [(p["workcenter_id"], p["lane"]) for p in released])
        # Пистата 2 е свободна за другия веднага, без да чака изтичането.
        y = self._wo(self.wc_two, WEDNESDAY, 9, crew_lane=2)
        result = y.with_user(self.mrp_user2).crew_drop(
            self.wc_two.id, 2, date_start=self._utc(WEDNESDAY, 13)
        )
        self.assertEqual(result["status"], "done")

    def test_r38_drop_releases_every_lane_of_the_drag(self):
        """Пускането става преди ping към последната цел (ping-ът е
        ограничен до 4 в секунда): писта 2 е хваната от последния ping,
        а пускането е на друга машина."""
        x = self._wo(self.wc_two, TUESDAY, 9)
        Lock = self.Lock.with_user(self.mrp_user)
        Lock.crew_lane_acquire(self.wc_two.id, 1, workorder_id=x.id, tab="t1")
        Lock.crew_lane_ping(
            self.wc_two.id, 1, workorder_id=x.id, target_workcenter_id=self.wc_two.id,
            target_lane=2, tab="t1",
        )
        # Чужда ключалка на друга поръчка не се пипа.
        other = self._wo(self.wc_pg, WEDNESDAY, 9)
        Lock.crew_lane_acquire(self.wc_pg.id, 1, workorder_id=other.id, tab="t2")
        result = x.with_user(self.mrp_user).crew_drop(
            self.wc_other.id, 1, date_start=self._utc(TUESDAY, 13)
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(x.workcenter_id, self.wc_other)
        self.assertEqual(self._held(self.mrp_user), {(self.wc_pg, 1)})
        y = self._wo(self.wc_two, WEDNESDAY, 9, crew_lane=2)
        result = y.with_user(self.mrp_user2).crew_drop(
            self.wc_two.id, 2, date_start=self._utc(WEDNESDAY, 13)
        )
        self.assertEqual(result["status"], "done")


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReviewPingPayload(CrewLanesCommon):
    """Находка 3 (Р38): ping-ът казва какво държи, с изтичането на влачещия."""

    def test_r38_refused_target_is_not_reported_as_locked(self):
        with freeze_time("2026-10-05 07:59:30"):
            self.Lock.with_user(self.mrp_user).crew_lane_acquire(self.wc_two.id, 1)
        Lock2 = self.Lock.with_user(self.mrp_user2)
        self.assertTrue(Lock2.crew_lane_acquire(self.wc_two.id, 2)["ok"])
        result = Lock2.crew_lane_ping(
            self.wc_two.id, 2, target_workcenter_id=self.wc_two.id, target_lane=1, tab="t2"
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["user"], self.mrp_user.name)
        _channel, payload = self._bus("mrp_crew_lane/drag")[-1]
        self.assertEqual(
            (payload["source_locked"], payload["target_locked"]), (True, False)
        )
        # Изтичането е на влачещия (08:01:00), не на държателя (08:00:30).
        self.assertEqual(payload["expires_at"], "2026-10-05 08:01:00")

    def test_r38_source_held_by_another(self):
        self.Lock.with_user(self.mrp_user).crew_lane_acquire(self.wc_two.id, 1)
        self.Lock.with_user(self.mrp_user2).crew_lane_ping(self.wc_two.id, 1, tab="t2")
        _channel, payload = self._bus("mrp_crew_lane/drag")[-1]
        self.assertEqual(
            (payload["source_locked"], payload["target_locked"]), (False, False)
        )


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReviewStartLane(CrewLanesCommon):
    """Находка 4 (Р29, M14.4): стартът търси писта без започнати."""

    def test_r29_start_pushes_unstarted_instead_of_overlapping_started(self):
        s1 = self._wo(self.wc_two, MONDAY, 10, minutes=240)
        self.assertEqual(s1.crew_lane, 1)
        s1.state = "progress"
        u3 = self._wo(self.wc_two, MONDAY, 11, 30, crew_lane=2)
        x = self._wo(self.wc_two, TUESDAY, 9)
        self.assertEqual(x.crew_lane, 1)
        x.button_start(bypass=True)
        self.assertEqual(x.state, "progress")
        self.assertSlot(x, MONDAY, 11, MONDAY, 12)
        self.assertEqual(x.crew_lane, 2)
        # U3 е избутана след X — през обяда, на 13–14.
        self.assertEqual(u3.crew_lane, 2)
        self.assertSlot(u3, MONDAY, 13, MONDAY, 14)
        self.assertSlot(s1, MONDAY, 10, MONDAY, 14)
        self.assertEqual(s1.crew_lane, 1)
        self.assertFalse(self._notes(x.production_id, "Lane overflow"))

    def test_r29_start_prefers_a_free_lane(self):
        """Свободната писта е по-добра от избутване: X прескача в нея."""
        s1 = self._wo(self.wc_two, MONDAY, 10, minutes=240)
        s1.state = "progress"
        x = self._wo(self.wc_two, TUESDAY, 9)
        x.button_start(bypass=True)
        self.assertEqual(x.crew_lane, 2)
        self.assertSlot(x, MONDAY, 11, MONDAY, 12)

    def test_r29_start_all_lanes_started_overflows(self):
        s1 = self._wo(self.wc_two, MONDAY, 10, minutes=240)
        s1.state = "progress"
        s2 = self._wo(self.wc_two, MONDAY, 10, 30, minutes=240, crew_lane=2)
        s2.state = "progress"
        x = self._wo(self.wc_two, TUESDAY, 9)
        x.button_start(bypass=True)
        self.assertEqual(x.crew_lane, 1)
        self.assertTrue(self._notes(x.production_id, "Lane overflow"))


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReviewLateStart(CrewLanesCommon):
    """Находка 5 (Р37, Р34): късният старт пази дължината на поръчката."""

    def setUp(self):
        super().setUp()
        self.wc_pg.write(
            {"crew_max_stretch_hours": 0.5, "crew_responsible_id": self.mrp_user.id}
        )

    def test_r37_late_start_after_the_planned_end(self):
        x = self._wo(self.wc_pg, MONDAY, 7)
        x.button_start(bypass=True)
        self.assertSlot(x, MONDAY, 11, MONDAY, 12)
        self.assertEqual(x.crew_planned_finish, self._utc(MONDAY, 12))
        self.assertEqual(x.duration_expected, 60.0)
        # 40-ата минута от 60: нито разтягане, нито тревога.
        with freeze_time("2026-10-05 08:40:00"):
            record = x.crew_train_preview()["records"].get(x.id, {})
            self.assertFalse(record.get("overstretched"))
            self.assertFalse(record.get("stretch_hours"))
            self.wc_pg._crew_train(self._utc(MONDAY, 11, 40))
        self.assertFalse(x.crew_is_overstretched)
        self.assertEqual(x.crew_stretch_alert_level, 0)
        self.assertFalse(self._notes(x.production_id, "past its planned end"))
        self.assertSlot(x, MONDAY, 11, MONDAY, 12)

    def test_r37_late_start_before_the_planned_end(self):
        """Планирана 10:30–11:30, стартирана в 11:00: краят е 12:00, не 11:30."""
        x = self._wo(self.wc_pg, MONDAY, 10, 30)
        nxt = self._wo(self.wc_pg, MONDAY, 11, 30)
        x.button_start(bypass=True)
        self.assertSlot(x, MONDAY, 11, MONDAY, 12)
        self.assertEqual(x.crew_planned_finish, self._utc(MONDAY, 12))
        # Следващата в пистата е избутана след реалния край (през обяда).
        self.assertSlot(nxt, MONDAY, 13, MONDAY, 14)

    def test_r37_late_start_over_the_lunch(self):
        """Стартирана в 11:30: 30 мин до обяда + 30 мин след него."""
        x = self._wo(self.wc_pg, MONDAY, 7)
        with freeze_time("2026-10-05 08:30:00"):
            x.button_start(bypass=True)
        self.assertSlot(x, MONDAY, 11, MONDAY, 13, minute=30, end_minute=30)
        self.assertEqual(x.crew_planned_finish, self._utc(MONDAY, 13, 30))
