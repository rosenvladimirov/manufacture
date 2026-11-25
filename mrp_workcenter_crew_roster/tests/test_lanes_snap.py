# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""19.0.1.6.1 — Р32, допълнение на Росен от 09.10: „дори и да пусна далеч
назад, ако има работни часове, трябва да се лепи до последния ВО … ако след
последния има почивка — веднага след почивката“.

Пускане в ПРАЗНО място от нашия Гант (`crew_drop(..., snap=True)`, без
`after`) не оставя дупка: X залепва за края на последната поръчка в пистата
преди мястото на пускане; ако веднага след нея е неработно време — в
началото на следващото работно време; без предходна — от сега. Без `snap`
(пряк запис, вмъкване при k = 0) — както досега, на `date_start`.

Календарът е на Полигруп (08–12, обяд 12–13, 13–17); „сега“ е понеделник
05.10.2026 11:00 местно време."""
from freezegun import freeze_time

from odoo.tests import tagged

from .common import MONDAY
from .test_lanes import FROZEN_NOW, TUESDAY, WEDNESDAY, CrewLanesCommon

THURSDAY = WEDNESDAY + (WEDNESDAY - TUESDAY)


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestDropSnap(CrewLanesCommon):
    def _drop(self, x, day, hour, snap=True):
        return x.crew_drop(self.wc_pg.id, 1, date_start=self._utc(day, hour), snap=snap)

    def test_snap_far_after_the_last_sticks_to_it(self):
        """Пуснато далеч след последната (вторник 15:00) → залепва в 10:00."""
        a = self._wo(self.wc_pg, TUESDAY, 8)
        b = self._wo(self.wc_pg, TUESDAY, 9)
        x = self._wo(self.wc_pg, THURSDAY, 8)
        result = self._drop(x, TUESDAY, 15)
        self.assertEqual(result["status"], "done")
        self.assertSlot(x, TUESDAY, 10, TUESDAY, 11, second=1)
        # Предходните не мърдат.
        self.assertSlot(a, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(b, TUESDAY, 9, TUESDAY, 10)

    def test_snap_after_the_end_of_the_shift_goes_to_the_next_morning(self):
        """Последната свършва в 17:00 (краят на смяната) → 08:00 на
        следващия работен ден."""
        self._wo(self.wc_pg, TUESDAY, 16)
        x = self._wo(self.wc_pg, THURSDAY, 13)
        self._drop(x, WEDNESDAY, 14)
        self.assertSlot(x, WEDNESDAY, 8, WEDNESDAY, 9)

    def test_snap_after_lunch(self):
        """Последната свършва в 12:00 (обяд) → 13:00."""
        self._wo(self.wc_pg, TUESDAY, 11)
        x = self._wo(self.wc_pg, THURSDAY, 8)
        self._drop(x, TUESDAY, 16)
        self.assertSlot(x, TUESDAY, 13, TUESDAY, 14)

    def test_snap_without_previous_starts_now(self):
        """Без предходна поръчка в пистата → от сега (понеделник 11:00)."""
        x = self._wo(self.wc_pg, THURSDAY, 8)
        self._drop(x, WEDNESDAY, 14)
        self.assertSlot(x, MONDAY, 11, MONDAY, 12)

    def test_snap_ignores_wagons_after_the_place(self):
        """Поръчките след мястото на пускане не са „предходни“ и не мърдат."""
        a = self._wo(self.wc_pg, TUESDAY, 8)
        c = self._wo(self.wc_pg, TUESDAY, 16)
        x = self._wo(self.wc_pg, THURSDAY, 8)
        self._drop(x, TUESDAY, 13)
        self.assertSlot(x, TUESDAY, 9, TUESDAY, 10, second=1)
        self.assertSlot(a, TUESDAY, 8, TUESDAY, 9)
        self.assertSlot(c, TUESDAY, 16, TUESDAY, 17)

    def test_without_snap_stays_where_dropped(self):
        """Без `snap` (не е свободно пускане от Ганта) — на `date_start`."""
        self._wo(self.wc_pg, TUESDAY, 8)
        x = self._wo(self.wc_pg, THURSDAY, 8)
        self._drop(x, TUESDAY, 15, snap=False)
        self.assertSlot(x, TUESDAY, 15, TUESDAY, 16)
