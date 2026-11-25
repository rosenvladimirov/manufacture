# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""№142 на Теолино: изборът „неработното време“ в Ганта е на потребителя."""
from freezegun import freeze_time

from odoo.tests import tagged

from .test_lanes import FROZEN_NOW, CrewLanesCommon


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestGanttOffTime(CrewLanesCommon):
    def _gantt(self, user, groupby):
        return (
            self.env["mrp.workorder"]
            .with_user(user)
            .get_gantt_data(
                [("workcenter_id", "in", [self.wc_two.id])],
                groupby,
                {"date_start": {}, "date_finished": {}},
                start_date="2026-10-04 21:00:00",
                stop_date="2026-10-11 21:00:00",
                scale="week",
            )
        )

    def test_hidden_by_default_and_remembered_per_user(self):
        self.assertFalse(self._gantt(self.mrp_user, ["workcenter_id", "crew_lane"])["crew_show_off_time"])
        # Обикновен потребител на производството превключва за себе си.
        self.env["res.users"].with_user(self.mrp_user).crew_gantt_set_show_off_time(True)
        self.assertTrue(self.mrp_user.crew_gantt_show_off_time)
        self.assertTrue(self._gantt(self.mrp_user, ["workcenter_id", "crew_lane"])["crew_show_off_time"])
        # Изборът не е за всички: другият потребител остава със скритото време.
        self.assertFalse(self._gantt(self.mrp_user2, ["workcenter_id", "crew_lane"])["crew_show_off_time"])
        self.env["res.users"].with_user(self.mrp_user).crew_gantt_set_show_off_time(False)
        self.assertFalse(self.mrp_user.crew_gantt_show_off_time)
