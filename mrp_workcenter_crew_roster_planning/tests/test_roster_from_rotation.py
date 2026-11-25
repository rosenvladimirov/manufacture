# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Нарядът по център от смяната на бригадата (Росен 14.10.2026).

Центърът е закачен за ротацията и взема календара ѝ (07–19 и 19–07); при
генериране на смените нарядът на всяка смяна на центъра е цялата бригада на
смяна, със заместника при отпуск.
"""
from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged

from odoo.addons.planning_crew_rotation.tests.test_crew_rotation import _with_contract

ANCHOR = date(2026, 11, 1)


@tagged("post_install", "-at_install")
class TestRosterFromRotation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, lang="en_US", tz="Europe/Sofia"))
        env = cls.env
        env.user.tz = "Europe/Sofia"
        attendances = []
        for dow in range(7):
            for start, stop in ((0, 7), (7, 19), (19, 24)):
                attendances.append((0, 0, {
                    "name": "%s %s-%s" % (dow, start, stop), "dayofweek": str(dow),
                    "hour_from": start, "hour_to": stop,
                    "day_period": "morning" if start < 12 else "afternoon"}))
        cls.calendar = env["resource.calendar"].create({
            "name": "Continuous 2x12 (roster test)", "tz": "Europe/Sofia",
            "attendance_ids": [(5, 0, 0)] + attendances})
        Template = env["planning.slot.template"]
        day = Template.create({"start_time": 7.0, "end_time": 19.0, "duration_days": 1})
        night = Template.create({"start_time": 19.0, "end_time": 7.0, "duration_days": 2})
        cls.rotation = env["planning.crew.rotation"].create({
            "name": "Extrusion (roster test)", "calendar_id": cls.calendar.id,
            "day_template_id": day.id, "night_template_id": night.id,
            "anchor_date": ANCHOR, "preset": "2-2-4"})
        cls.rotation.action_load_preset()
        cls.rotation.action_approve()
        cls.crews = cls.rotation.crew_ids.sorted("offset_days")
        cls.members = {}
        for crew in cls.crews:
            people = _with_contract(env, [
                {"name": "%s worker %s" % (crew.code, i), "tz": "Europe/Sofia"} for i in (1, 2)])
            for person in people:
                env["planning.crew.membership"].create({
                    "contract_id": person.contract_id.id, "crew_id": crew.id, "date_from": ANCHOR})
            cls.members[crew] = people
        cls.extruder = env["mrp.workcenter"].create({
            "name": "Extruder (roster test)", "crew_rotation_id": cls.rotation.id})
        cls.substitute = _with_contract(env, {"name": "Substitute", "tz": "Europe/Sofia"})
        cls.leave_type = env["hr.leave.type"].create({
            "name": "Leave (roster test)", "requires_allocation": "no",
            "leave_validation_type": "no_validation"})

    def _rosters(self, day=None):
        domain = [("workcenter_id", "=", self.extruder.id)]
        if day:
            domain.append(("date", "=", day))
        return self.env["mrp.workcenter.roster"].search(domain)

    def test_work_center_takes_the_schedule_of_the_rotation(self):
        self.assertEqual(self.extruder.resource_calendar_id, self.calendar)
        keys = [b["key"] for b in self.extruder._crew_shift_blocks_for_date(ANCHOR)]
        self.assertEqual(keys, ["07:00", "19:00"])

    def test_the_crew_on_shift_fills_the_roster(self):
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7))
        self.assertEqual(counts["rosters_created"], 16)
        rosters = self._rosters(ANCHOR)
        self.assertEqual(sorted(rosters.mapped("shift_key")), ["07:00", "19:00"])
        day = rosters.filtered(lambda r: r.shift_key == "07:00")
        # 1 ноември: позицията е отместването; DDNNRRRR — A (0) е дневна, B (2) — нощна
        self.assertEqual(day.crew_id, self.crews[0])
        self.assertEqual(day.employee_ids, self.members[self.crews[0]])
        night = rosters.filtered(lambda r: r.shift_key == "19:00")
        self.assertEqual(night.employee_ids, self.members[self.crews[1]])

    def test_generate_again_keeps_the_rosters(self):
        self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7))
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=7))
        self.assertEqual((counts["rosters_created"], counts["rosters_updated"],
                          counts["rosters_deleted"]), (0, 0, 0))

    def test_substitute_is_in_the_roster_of_the_absent(self):
        absent = self.members[self.crews[0]][0]
        absent.crew_substitute_ids = self.substitute
        self.env["hr.leave"].create({
            "employee_id": absent.id, "holiday_status_id": self.leave_type.id,
            "request_date_from": ANCHOR + timedelta(days=1),
            "request_date_to": ANCHOR + timedelta(days=1)})
        self.rotation._crew_generate(ANCHOR, ANCHOR + timedelta(days=1))
        roster = self._rosters(ANCHOR + timedelta(days=1)).filtered(
            lambda r: r.shift_key == "07:00")
        self.assertNotIn(absent, roster.employee_ids)
        self.assertIn(self.substitute, roster.employee_ids)
        self.assertEqual(len(roster.employee_ids), 2)

    def test_roster_changed_by_hand_is_kept(self):
        self.rotation._crew_generate(ANCHOR, ANCHOR)
        roster = self._rosters(ANCHOR).filtered(lambda r: r.shift_key == "07:00")
        roster.employee_ids = self.substitute
        self.assertTrue(roster.crew_manual)
        counts = self.rotation._crew_generate(ANCHOR, ANCHOR)
        self.assertEqual(counts["rosters_manual"], 1)
        self.assertEqual(roster.employee_ids, self.substitute)
