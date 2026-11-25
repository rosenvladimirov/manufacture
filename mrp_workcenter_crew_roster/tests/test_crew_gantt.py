# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .common import MONDAY, CrewWorkorderCommon

# Стандартните условия на декорациите на EE Ганта (mrp_workorder_view_gantt):
# нашият изглед трябва да ги запази (Ф10).
STD_DANGER = "json_popover and 'text-danger' in json_popover"
STD_WARNING_CANCEL = "state == 'cancel'"
STD_WARNING_POPOVER = "json_popover and 'text-warning' in json_popover"

# Действията на модула, чиито контексти не бива да носят default_* (Ф3).
CREW_ACTIONS = (
    "mrp_workcenter_crew_roster.mrp_workcenter_plan_select_action",
    "mrp_workcenter_crew_roster.mrp_workcenter_plan_select_roster_action",
    "mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_action",
    "mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_employee_action",
    "mrp_workcenter_crew_roster.mrp_workcenter_roster_action",
)


@tagged("post_install", "-at_install", "crew_roster")
class TestCrewGanttGuard(CrewWorkorderCommon):
    """Тест 10 от TECH_DESIGN §6, изменен от §9.8 т. 21 (1.5.0): гардът M10
    отпада (Р12 изменено) — с флага `crew_gantt_drag` поръчката МОЖЕ да
    отиде на друга машина със свободна писта; заета писта → грешка (M16 →
    M14.3 + M15)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wc_other = cls._make_workcenter("WC Other", cls.cal_pg)

    def _wo(self):
        return self._make_wo(self.wc_pg, self._utc(MONDAY, 9))

    def test_drag_to_other_workcenter_free_lane_passes(self):
        """Друга машина със свободна писта в това време — минава."""
        wo = self._wo()
        wo.with_context(crew_gantt_drag=True).write({"workcenter_id": self.wc_other.id})
        self.assertEqual(wo.workcenter_id, self.wc_other)

    def test_drag_to_other_workcenter_busy_raises(self):
        """Друга машина, чиято писта е заета в това време — грешка, нищо не
        е преместено."""
        self._make_wo(self.wc_other, self._utc(MONDAY, 9))
        wo = self._wo()
        with self.assertRaises(ValidationError) as catcher:
            wo.with_context(crew_gantt_drag=True).write(
                {"workcenter_id": self.wc_other.id}
            )
        self.assertIn("never overlap", str(catcher.exception))
        self.assertEqual(wo.workcenter_id, self.wc_pg)

    def test_write_without_flag_moves(self):
        """Формата, отворена от Ганта, и всички други пътища — без флага."""
        wo = self._wo()
        wo.write({"workcenter_id": self.wc_other.id})
        self.assertEqual(wo.workcenter_id, self.wc_other)

    def test_action_context_is_not_the_flag(self):
        """Контекстът на действието (`crew_workcenter_id`) не е флагът (Ф3)."""
        wo = self._wo()
        wo.with_context(crew_workcenter_id=self.wc_pg.id).write(
            {"workcenter_id": self.wc_other.id}
        )
        self.assertEqual(wo.workcenter_id, self.wc_other)

    def test_drag_same_workcenter_and_dates_pass(self):
        """С флага: същият център и новите дати минават."""
        wo = self._wo()
        start = self._utc(MONDAY, 13)
        wo.with_context(crew_gantt_drag=True).write(
            {
                "workcenter_id": self.wc_pg.id,
                "date_start": start,
                "date_finished": self._utc(MONDAY, 14),
            }
        )
        self.assertEqual(wo.workcenter_id, self.wc_pg)
        self.assertEqual(wo.date_start, start)

    def test_drag_batch_one_busy_raises(self):
        """Пакетен запис: една поръчка, която влиза в заета писта, стига за
        грешката; без застъпване пакетът минава."""
        wo1 = self._wo()
        wo2 = self._make_wo(self.wc_other, self._utc(MONDAY, 9, 30))
        with self.assertRaises(ValidationError):
            (wo1 | wo2).with_context(crew_gantt_drag=True).write(
                {"workcenter_id": self.wc_pg.id}
            )
        self.assertEqual(wo2.workcenter_id, self.wc_other)
        wo3 = self._make_wo(self.wc_other, self._utc(MONDAY, 11))
        (wo1 | wo3).with_context(crew_gantt_drag=True).write(
            {"workcenter_id": self.wc_pg.id}
        )
        self.assertEqual(wo3.workcenter_id, self.wc_pg)


@tagged("post_install", "-at_install", "crew_roster")
class TestCrewGanttViews(CrewWorkorderCommon):
    """Изгледите, действията и менютата на Ганта „Планирай център“ (§4)."""

    def _gantt_node(self, view_id=None):
        view = self.env["mrp.workorder"].get_view(view_id=view_id, view_type="gantt")
        return view["id"], etree.fromstring(view["arch"])

    def test_crew_names_for_popover(self):
        wo = self._make_wo(
            self.wc_pg, self._utc(MONDAY, 9), crew=self.emp1 | self.emp2
        )
        self.assertEqual(wo.crew_names, "Crew One, Crew Two")
        wo.employee_assigned_ids = False
        self.assertFalse(wo.crew_names)

    def test_crew_gantt_is_not_the_default(self):
        """Ф10: без view_id стандартният Гант остава подразбиращият се."""
        ours = self.env.ref("mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_view")
        view_id, node = self._gantt_node()
        self.assertNotEqual(view_id, ours.id)
        self.assertNotEqual(node.get("js_class"), "mrp_crew_gantt")
        self.assertEqual(ours.mode, "primary")

    def test_crew_gantt_arch(self):
        ours = self.env.ref("mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_view")
        view_id, node = self._gantt_node(ours.id)
        self.assertEqual(view_id, ours.id)
        self.assertEqual(node.get("js_class"), "mrp_crew_gantt")
        # §9.8 т. 21 (1.5.0): групирането е център → писта (Р29, Р31).
        self.assertEqual(node.get("default_group_by"), "workcenter_id,crew_lane")
        self.assertIn("'day': 'hour:quarter'", node.get("precision"))
        self.assertEqual(node.get("dependency_field"), "blocked_by_workorder_ids")
        self.assertEqual(
            node.get("dependency_inverted_field"), "needed_by_workorder_ids"
        )
        self.assertEqual(
            node.get("progress_bar"), "workcenter_id,employee_assigned_ids"
        )
        danger = node.get("decoration-danger")
        warning = node.get("decoration-warning")
        self.assertIn("is_late", danger)
        self.assertIn(STD_DANGER, danger)
        self.assertIn("is_overloaded", warning)
        self.assertIn(STD_WARNING_CANCEL, warning)
        self.assertIn(STD_WARNING_POPOVER, warning)
        names = {field.get("name") for field in node.iter("field")}
        self.assertTrue(
            {
                "is_late",
                "is_overloaded",
                "deadline",
                "crew_names",
                "json_popover",
                "crew_lane",
                "crew_is_overstretched",
                "crew_planned_finish",
            }
            <= names
        )

    def test_standard_gantt_untouched(self):
        """Стандартният Гант не получава нищо от модула."""
        std = self.env.ref("mrp_workorder.mrp_workorder_view_gantt")
        _view_id, node = self._gantt_node(std.id)
        self.assertEqual(node.get("js_class"), "mrp_workorder_gantt")
        self.assertNotIn("is_late", node.get("decoration-danger") or "")

    def test_actions_without_default_context(self):
        """Ф3: никое действие на модула не носи default_* в контекста."""
        for xmlid in CREW_ACTIONS:
            action = self.env.ref(xmlid)
            context = safe_eval(action.context or "{}", {"uid": self.env.uid})
            self.assertFalse(
                [key for key in context if key.startswith("default_")], xmlid
            )
        for action in (
            self.wc_pg.action_crew_plan_gantt(),
            self.env["mrp.workcenter.plan.select"]
            .create({"workcenter_ids": [(6, 0, self.wc_pg.ids)]})
            .action_open_gantt(),
        ):
            self.assertFalse(
                [key for key in action["context"] if key.startswith("default_")]
            )

    def test_plan_gantt_action(self):
        """Smart бутонът „Plan“ и изборът на център: нашият Гант, филтърът
        по центъра и центърът за „Recompute“."""
        ours = self.env.ref("mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_view")
        action = (
            self.env["mrp.workcenter.plan.select"]
            .create({"workcenter_ids": [(6, 0, self.wc_pg.ids)]})
            .action_open_gantt()
        )
        self.assertEqual(action["res_model"], "mrp.workorder")
        view_id = action["view_id"]
        if isinstance(view_id, (list, tuple)):
            view_id = view_id[0]
        self.assertEqual(view_id, ours.id)
        self._assert_crew_gantt_context(
            action["context"],
            {
                "search_default_workcenter_id": self.wc_pg.id,
                "crew_workcenter_id": self.wc_pg.id,
            },
        )
        self._assert_same_crew_gantt_action(action, self.wc_pg.action_crew_plan_gantt())

    def test_employee_action_without_workcenter(self):
        """„Work Orders by Employee“: нашият Гант, без център в контекста
        (бутонът „Recompute“ не се показва), групиран по служител."""
        ours = self.env.ref("mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_view")
        action = self.env.ref(
            "mrp_workcenter_crew_roster.mrp_workorder_crew_gantt_employee_action"
        )
        self.assertEqual(action.view_id, ours)
        self.assertFalse(action.domain)
        context = safe_eval(action.context or "{}")
        self.assertNotIn("crew_workcenter_id", context)
        self.assertEqual(context.get("group_by"), ["employee_assigned_ids"])

    def test_menus(self):
        menus = {
            "menu_mrp_workcenter_plan_select": "mrp_workcenter_plan_select_action",
            "menu_mrp_workcenter_roster": "mrp_workcenter_plan_select_roster_action",
            "menu_mrp_workorder_crew_gantt_employee": (
                "mrp_workorder_crew_gantt_employee_action"
            ),
        }
        planning = self.env.ref("mrp.mrp_planning_menu_root")
        for menu_xmlid, action_xmlid in menus.items():
            menu = self.env.ref("mrp_workcenter_crew_roster." + menu_xmlid)
            self.assertEqual(menu.parent_id, planning)
            self.assertEqual(
                menu.action, self.env.ref("mrp_workcenter_crew_roster." + action_xmlid)
            )
