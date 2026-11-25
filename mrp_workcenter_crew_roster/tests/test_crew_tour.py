# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import datetime, time, timedelta

from pytz import timezone, utc

from odoo import Command, fields
from odoo.tests import HttpCase, new_test_user, tagged

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TZ = "Europe/Sofia"


@tagged("post_install", "-at_install", "-standard", "crew_roster_tour")
class TestCrewTour(HttpCase):
    """Тест 35 (TECH_DESIGN §9.13.5): tour-ът „Rearrange Plan“ → Undo.

    Не е в стандартния пуск (`-standard`): нужен е браузър. Пуска се изрично
    с `--test-tags crew_roster_tour`. Потребителят е MRP User (не admin) —
    така tour-ът проверява и правата.

    Данни: център с 7-дневен календар и две незапочнати поръчки ПРЕДИ два
    дни (часовникът е истинският — браузърът не се мокира): A (срокът е
    по-късно) е първа, B (срокът е по-рано) — втора. Съветникът ги мести
    напред; след Undo те са по старите места до секунда.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tz = timezone(TZ)
        attendances = []
        for dow in range(7):
            attendances += [
                Command.create(
                    {
                        "name": "%s Morning" % DAYS[dow],
                        "dayofweek": str(dow),
                        "hour_from": 8,
                        "hour_to": 12,
                        "day_period": "morning",
                    }
                ),
                Command.create(
                    {
                        "name": "%s Afternoon" % DAYS[dow],
                        "dayofweek": str(dow),
                        "hour_from": 13,
                        "hour_to": 17,
                        "day_period": "afternoon",
                    }
                ),
            ]
        calendar = cls.env["resource.calendar"].create(
            {"name": "Tour - 7 days", "tz": TZ, "attendance_ids": attendances}
        )
        cls.workcenter = cls.env["mrp.workcenter"].create(
            {"name": "Tour Line", "resource_calendar_id": calendar.id, "crew_snap_head": False}
        )
        cls.planner = new_test_user(
            cls.env,
            login="crew_planner",
            email="crew_planner@crew-test.invalid",
            groups="mrp.group_mrp_user,mrp.group_mrp_routings",
            company_id=cls.env.company.id,
            company_ids=[Command.set(cls.env.company.ids)],
            tz=TZ,
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Tour Bag", "type": "consu"}
        )
        today = fields.Date.context_today(cls.env.user.with_context(tz=TZ))
        past = today - timedelta(days=2)
        cls.wo_a = cls._make_wo(past, 9, deadline=today + timedelta(days=20))
        cls.wo_b = cls._make_wo(past, 10, deadline=today + timedelta(days=5))

    @classmethod
    def _utc(cls, day, hour):
        """Местен час (Europe/Sofia) → UTC без tz, както се пази в базата."""
        local = cls.tz.localize(datetime.combine(day, time(hour)))
        return local.astimezone(utc).replace(tzinfo=None)

    @classmethod
    def _make_wo(cls, day, hour, deadline):
        """Незапочната поръчка от 60 минути на `day` от `hour` (местно)."""
        production = cls.env["mrp.production"].create(
            {
                "product_id": cls.product.id,
                "product_qty": 1.0,
                "date_deadline": cls._utc(deadline, 12),
            }
        )
        production.action_confirm()
        start = cls._utc(day, hour)
        # Като `overlap=True` в common.py: поръчката влиза без проверката на
        # пистите (заварен план), както в test_wizard.
        return (
            cls.env["mrp.workorder"]
            .with_context(crew_lane_defer=True)
            .create(
                {
                    "name": "Tour operation",
                    "workcenter_id": cls.workcenter.id,
                    "production_id": production.id,
                    "product_uom_id": cls.product.uom_id.id,
                    "duration_expected": 60.0,
                    "date_start": start,
                    "date_finished": start + timedelta(minutes=60),
                }
            )
            .with_env(cls.env)
        )

    def _plan(self, workorder):
        return (
            workorder.workcenter_id,
            workorder.date_start,
            workorder.date_finished,
            workorder.crew_lane,
        )

    def test_35_rearrange_and_undo(self):
        """35: Plan Work Center → Гант → Rearrange Plan → потвърждение →
        отчет → Undo; после пак съветникът и Undo от известието в Ганта.
        Поръчките са на старите места; двете партиди са `wizard`/`undone`."""
        before = {wo: self._plan(wo) for wo in self.wo_a | self.wo_b}
        self.start_tour("/odoo", "crew_roster_replan_tour", login="crew_planner")
        batches = self.env["mrp.workcenter.replan.batch"].search(
            [("user_id", "=", self.planner.id)]
        )
        # Две партиди: Undo от отчета и Undo от известието в Ганта.
        self.assertEqual(len(batches), 2)
        for batch in batches:
            self.assertEqual((batch.source, batch.state), ("wizard", "undone"))
            # Съветникът наистина е местил (иначе Undo не доказва нищо).
            moved = batch.line_ids.filtered(lambda line: line.result == "moved")
            self.assertEqual(moved.workorder_id, self.wo_a | self.wo_b)
        self.env.invalidate_all()
        for wo, plan in before.items():
            self.assertEqual(self._plan(wo), plan, wo.display_name)
