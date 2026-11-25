# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import datetime, time, timedelta

from pytz import utc

from odoo.tests import tagged

from .common import MONDAY, CrewRosterCommon


@tagged("post_install", "-at_install", "crew_roster")
class TestShiftBlocks(CrewRosterCommon):
    """Тест 2 от TECH_DESIGN §6: блоковете на смените (M1)."""

    def _week_blocks(self, workcenter):
        tz = workcenter._crew_calendar_tz()
        dt_from = tz.localize(datetime.combine(MONDAY, time.min))
        dt_to = dt_from + timedelta(days=7)
        return workcenter._crew_shift_blocks(dt_from, dt_to)

    def test_polygroup_calendar_one_block_per_day(self):
        """08–12, обяд 12–13, 13–17, 7 дни → по ЕДИН блок „08:00“ на ден."""
        blocks = self._week_blocks(self.wc_pg)
        self.assertEqual(len(blocks), 7, "7 дни не се сливат и обядът не реже")
        self.assertEqual({b["key"] for b in blocks}, {"08:00"})
        self.assertEqual(
            [b["date"] for b in blocks],
            [MONDAY + timedelta(days=i) for i in range(7)],
        )
        for block in blocks:
            self.assertAlmostEqual(block["hours"], 8.0, msg="обядът е извън часовете")
            self.assertEqual(block["start"].strftime("%H:%M"), "08:00")
            self.assertEqual(block["stop"].strftime("%H:%M"), "17:00")
            self.assertEqual(len(block["intervals"]), 2)

    def test_two_by_twelve_two_blocks_per_day(self):
        """Р28: 08–20 / 20–08 → точно два блока на денонощие, нощният през полунощ."""
        blocks = self._week_blocks(self.wc_2x12)
        self.assertEqual(len(blocks), 14)
        for i in range(7):
            day = MONDAY + timedelta(days=i)
            day_blocks = [b for b in blocks if b["date"] == day]
            self.assertEqual([b["key"] for b in day_blocks], ["08:00", "20:00"])
            day_shift, night_shift = day_blocks
            self.assertAlmostEqual(day_shift["hours"], 11.0)
            self.assertAlmostEqual(night_shift["hours"], 12.0)
            # Нощната минава през полунощ и свършва в 08:00 на следващия ден.
            self.assertEqual(night_shift["stop"].date(), day + timedelta(days=1))
            self.assertEqual(night_shift["stop"].strftime("%H:%M"), "08:00")
            self.assertEqual(day_shift["stop"].strftime("%H:%M"), "20:00")

    def test_adjacent_shifts_are_two_blocks(self):
        """06–14 и 14–22 се допират → две смени „06:00“ и „14:00“."""
        cal = self._make_calendar(
            "Two adjacent",
            [(0, 6, 14, "morning", "Early"), (0, 14, 22, "afternoon", "Late")],
        )
        wc = self._make_workcenter("WC adjacent", cal)
        self.assertEqual(self._keys(wc, MONDAY), ["06:00", "14:00"])

    def test_night_shift_belongs_to_start_day(self):
        """Пн 22–24 + Вт 00–06 → един блок „22:00“ на понеделник."""
        cal = self._make_calendar(
            "Night",
            [(0, 22, 24, "afternoon", "Night head"), (1, 0, 6, "morning", "Night tail")],
        )
        wc = self._make_workcenter("WC night", cal)
        blocks = wc._crew_shift_blocks_for_date(MONDAY)
        self.assertEqual([b["key"] for b in blocks], ["22:00"])
        self.assertEqual(blocks[0]["date"], MONDAY)
        self.assertAlmostEqual(blocks[0]["hours"], 8.0)
        self.assertEqual(blocks[0]["stop"].date(), MONDAY + timedelta(days=1))
        # Вторник няма своя смяна — 00–06 е продължение на нощната.
        self.assertEqual(self._keys(wc, MONDAY + timedelta(days=1)), [])

    def test_gap_threshold(self):
        """Празнина над прага → два блока; под прага → един."""
        cal = self._make_calendar(
            "Gap",
            [
                (0, 8, 12, "morning", "A"),
                (0, 14, 18, "afternoon", "B"),  # празнина 2 ч
                (1, 8, 12, "morning", "C"),
                (1, 12.5, 16, "afternoon", "D"),  # празнина 0,5 ч
            ],
        )
        wc = self._make_workcenter("WC gap", cal)
        self.assertEqual(self._keys(wc, MONDAY), ["08:00", "14:00"])
        self.assertEqual(self._keys(wc, MONDAY + timedelta(days=1)), ["08:00"])
        # По-голям праг → понеделник става една смяна.
        self.ICP.set_param("mrp_workcenter_crew_roster.shift_gap_hours", "3")
        self.assertEqual(self._keys(wc, MONDAY), ["08:00"])

    def test_renamed_line_keeps_key(self):
        """Преименуван ред в календара не сменя ключа и не чупи наряда."""
        roster = self.Roster.create(
            {
                "workcenter_id": self.wc_pg.id,
                "date": MONDAY,
                "shift_key": "08:00",
                "employee_ids": [(6, 0, self.emp1.ids)],
            }
        )
        monday_lines = self.cal_pg.attendance_ids.filtered(
            lambda a: a.dayofweek == "0"
        )
        monday_lines.write({"name": "Renamed shift"})
        self.assertEqual(self._keys(self.wc_pg, MONDAY), ["08:00"])
        self.assertFalse(roster.shift_missing)
        self.assertEqual(roster.shift_key, "08:00")

    def test_two_weeks_calendar(self):
        """two_weeks_calendar: седмица 0 — 08–16, седмица 1 — 14–22."""
        lines = []
        for dow in range(7):
            lines += [
                (dow, 8, 16, "morning", "Week A", "0"),
                (dow, 14, 22, "afternoon", "Week B", "1"),
            ]
        cal = self._make_calendar("Two weeks", lines, two_weeks_calendar=True)
        wc = self._make_workcenter("WC two weeks", cal)
        Attendance = self.env["resource.calendar.attendance"]
        for offset in (0, 7):
            day = MONDAY + timedelta(days=offset)
            expected = "08:00" if Attendance.get_week_type(day) == 0 else "14:00"
            self.assertEqual(self._keys(wc, day), [expected])

    def test_round_the_clock_calendar(self):
        """Календар „168“ (00–24 всеки ден) не става един безкраен блок:
        всеки ден е отделна смяна „00:00“ от 24 часа."""
        cal = self._make_calendar(
            "168", [(dow, 0, 24, "morning", "All day") for dow in range(7)]
        )
        wc = self._make_workcenter("WC 168", cal)
        blocks = self._week_blocks(wc)
        self.assertEqual(len(blocks), 7)
        self.assertEqual({b["key"] for b in blocks}, {"00:00"})
        for block in blocks:
            self.assertAlmostEqual(block["hours"], 24.0)

    def test_compute_leaves(self):
        """С compute_leaves отпускът на центъра се вади от часовете на блока."""
        tz = self.wc_pg._crew_calendar_tz()
        start = tz.localize(datetime.combine(MONDAY, time(9, 0)))
        self.env["resource.calendar.leaves"].create(
            {
                "name": "Maintenance",
                "calendar_id": self.cal_pg.id,
                "resource_id": self.wc_pg.resource_id.id,
                "date_from": start.astimezone(utc).replace(tzinfo=None),
                "date_to": (start + timedelta(hours=1))
                .astimezone(utc)
                .replace(tzinfo=None),
                "time_type": "leave",
            }
        )
        plain = self.wc_pg._crew_shift_blocks_for_date(MONDAY)
        with_leaves = self.wc_pg._crew_shift_blocks_for_date(
            MONDAY, compute_leaves=True
        )
        self.assertAlmostEqual(plain[0]["hours"], 8.0)
        self.assertAlmostEqual(with_leaves[0]["hours"], 7.0)
        self.assertEqual(with_leaves[0]["key"], "08:00")

    def test_flexible_calendar_has_no_blocks(self):
        """Гард: flexible календар не дава смени."""
        cal = self._make_calendar(
            "Flexible", [(0, 8, 17, "morning", "Any")], flexible_hours=True
        )
        wc = self._make_workcenter("WC flexible", cal)
        self.assertEqual(self._keys(wc, MONDAY), [])
