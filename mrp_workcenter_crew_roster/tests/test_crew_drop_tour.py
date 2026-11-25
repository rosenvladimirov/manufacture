# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import datetime, time, timedelta

from pytz import timezone, utc

from odoo import Command, fields
from odoo.tests import HttpCase, new_test_user, tagged

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# Хромът на тестовете е в UTC (сървърът пуска процесите с TZ=UTC), затова
# календарът и потребителят са в UTC: клетката „половин ден“ се реже в 12:00
# и A 08–12 | B 12–17 са долепени и на екрана, без лятно/зимно време.
TZ = "UTC"


@tagged("post_install", "-at_install", "-standard", "crew_roster_tour")
class TestCrewDropTour(HttpCase):
    """Тест 36 (дефект от живия тест 09.10, 19.0.1.6.1): пускане между два
    ДОЛЕПЕНИ вагона в истинския EE Гант (Р32).

    Център с календар 08–17 всеки ден и една писта; утре A 08–12 и B 12–17
    (A свършва точно когато B почва), вдругиден C 08–09 на същата писта.
    Гантът е по подразбиране (3 месеца, клетка = половин ден): A е в
    сутрешната клетка, B — в следобедната, долепени. Tour-ът влачи C с
    pointer събития, задържа го над границата A|B и проверява стрелката и
    призрака, после пуска. Тук: C е между A и B, B е избутана след C.
    Не е в стандартния пуск (`-standard`): нужен е браузър.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tz = timezone(TZ)
        attendances = [
            Command.create(
                {
                    "name": "%s" % DAYS[dow],
                    "dayofweek": str(dow),
                    "hour_from": 8,
                    "hour_to": 17,
                    "day_period": "morning",
                }
            )
            for dow in range(7)
        ]
        calendar = cls.env["resource.calendar"].create(
            {"name": "Drop Tour - 08-17", "tz": TZ, "attendance_ids": attendances}
        )
        cls.workcenter = cls.env["mrp.workcenter"].create(
            {"name": "Drop Line", "resource_calendar_id": calendar.id, "crew_snap_head": False}
        )
        cls.planner = new_test_user(
            cls.env,
            login="crew_dropper",
            email="crew_dropper@crew-test.invalid",
            groups="mrp.group_mrp_user,mrp.group_mrp_routings",
            company_id=cls.env.company.id,
            company_ids=[Command.set(cls.env.company.ids)],
            tz=TZ,
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Drop Bag", "type": "consu"}
        )
        cls.day = fields.Date.context_today(
            cls.env.user.with_context(tz=TZ)
        ) + timedelta(days=1)
        cls.wo_a = cls._make_wo("Wagon A", cls.day, 8, 240)
        cls.wo_b = cls._make_wo("Wagon B", cls.day, 12, 240)
        cls.wo_c = cls._make_wo("Wagon C", cls.day + timedelta(days=1), 8, 60)

    @classmethod
    def _utc(cls, day, hour):
        """Местен час (TZ) → UTC без tz, както се пази в базата."""
        local = cls.tz.localize(datetime.combine(day, time(hour)))
        return local.astimezone(utc).replace(tzinfo=None)

    @classmethod
    def _make_wo(cls, name, day, hour, minutes):
        """Незапочната поръчка `name` на `day` от `hour` (местно), `minutes` минути."""
        production = cls.env["mrp.production"].create(
            {"product_id": cls.product.id, "product_qty": 1.0}
        )
        production.action_confirm()
        start = cls._utc(day, hour)
        return (
            cls.env["mrp.workorder"]
            .with_context(crew_lane_defer=True)
            .create(
                {
                    "name": name,
                    "workcenter_id": cls.workcenter.id,
                    "production_id": production.id,
                    "product_uom_id": cls.product.uom_id.id,
                    "duration_expected": float(minutes),
                    "date_start": start,
                    "date_finished": start + timedelta(minutes=minutes),
                }
            )
            .with_env(cls.env)
        )

    def test_36_drop_between_adjacent_wagons(self):
        """36: стрелката на границата A|B, призракът „вмъкване“; след
        пускането C е между A и B, а B е избутана след C (Р32)."""
        a_start, a_stop = self.wo_a.date_start, self.wo_a.date_finished
        self.start_tour("/odoo", "crew_roster_drop_tour", login="crew_dropper")
        self.env.invalidate_all()
        # A не мърда; C почва секунда след края на A (CREW_GAP, Росен
        # 12.10.2026), краят ѝ — час след края на A; B — секунда след C.
        self.assertEqual((self.wo_a.date_start, self.wo_a.date_finished), (a_start, a_stop))
        self.assertEqual(self.wo_c.date_start, a_stop + timedelta(seconds=1))
        self.assertEqual(self.wo_c.date_finished, a_stop + timedelta(minutes=60))
        # B почва секунда след края на C (краят ѝ е по календара 08–17).
        self.assertEqual(self.wo_b.date_start, self.wo_c.date_finished + timedelta(seconds=1))
        self.assertGreater(self.wo_b.date_finished, self.wo_b.date_start)
        self.assertEqual(
            {wo.crew_lane for wo in self.wo_a | self.wo_b | self.wo_c}, {1}
        )

    def test_37_drop_in_empty_place_sticks_to_the_last(self):
        """37 (Р32, Росен 09.10): C е пусната далеч вдясно в празно място —
        не остава там, а залепва за края на последната поръчка (B); A и B
        не мърдат."""
        before = {
            wo: (wo.date_start, wo.date_finished) for wo in self.wo_a | self.wo_b
        }
        self.start_tour("/odoo", "crew_roster_drop_snap_tour", login="crew_dropper")
        self.env.invalidate_all()
        for wo, plan in before.items():
            self.assertEqual((wo.date_start, wo.date_finished), plan, wo.display_name)
        # Секунда след края на B (CREW_GAP, Росен 12.10.2026).
        self.assertEqual(self.wo_c.date_start, self.wo_b.date_finished + timedelta(seconds=1))
        self.assertEqual(self.wo_c.date_finished, self.wo_b.date_finished + timedelta(minutes=60))
        self.assertEqual(self.wo_c.crew_lane, 1)
