# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Shop Floor „Човеци“ / „Смяна/Бригада“ (Росен 15.10.2026): бригадите на смяната,
избраната бригада, добавяне с ПИН, махане, изритване, делене на труда."""
from datetime import datetime, timedelta

from odoo import Command
from odoo.tests import tagged

from .test_roster_from_rotation import ANCHOR, TestRosterFromRotation


@tagged("post_install", "-at_install")
class TestShopFloorShift(TestRosterFromRotation):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.crew_a, cls.crew_b = cls.crews[0], cls.crews[1]
        cls.leader_a = cls.members[cls.crew_a][0]
        cls.leader_b = cls.members[cls.crew_b][0]
        cls.leader_a.pin = "4321"
        cls.leader_b.pin = "1111"
        cls.crew_a.leader_id = cls.leader_a
        cls.crew_b.leader_id = cls.leader_b
        product = cls.env["product.product"].create({"name": "Film (shift test)", "is_storable": True})
        granule = cls.env["product.product"].create({"name": "Granule (shift test)"})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": product.product_tmpl_id.id, "product_id": product.id, "product_qty": 1.0,
            "bom_line_ids": [Command.create({"product_id": granule.id, "product_qty": 1.0})],
            "operation_ids": [Command.create({"name": "extrusion", "workcenter_id": cls.extruder.id,
                                              "time_cycle_manual": 60.0})],
        })
        cls.product = product

    def setUp(self):
        super().setUp()
        # членовете на бригадите са по назначения от ANCHOR (ноември) — местим ги от
        # вчера, за да са в бригадите си и днес
        memberships = self.env["planning.crew.membership"].search(
            [("crew_id", "in", (self.crew_a | self.crew_b).ids)])
        memberships.date_from = datetime.now().date() - timedelta(days=1)
        (self.members[self.crew_a] | self.members[self.crew_b])._compute_crew_id()
        self.session = {}
        self.Employee = self.env["hr.employee"].with_context(crew_shift_test_session=self.session)

    def _workorder(self):
        mo = self.env["mrp.production"].create({
            "product_id": self.product.id, "bom_id": self.bom.id, "product_qty": 1.0})
        mo.action_confirm()
        return mo.workorder_ids.with_context(crew_shift_test_session=self.session)

    def test_add_crew_only_with_the_leader_pin(self):
        self.assertEqual(self.Employee.crew_shift_add(self.crew_a.id, "0000")["error"], "pin")
        self.assertFalse(self.Employee.crew_shift_state()["crews"])
        self.assertTrue(self.Employee.crew_shift_add(self.crew_a.id, "4321")["ok"])
        state = self.Employee.crew_shift_state()
        self.assertEqual(state["mode"], "crew")
        self.assertEqual([c["id"] for c in state["crews"]], [self.crew_a.id])
        self.assertEqual(state["selected"], self.crew_a.id)
        self.assertEqual(self.session["session_owner"], self.leader_a.id)
        self.assertEqual(set(self.session["employees_connected"]), set(self.members[self.crew_a].ids))

    def test_crew_without_leader_is_refused(self):
        self.crews[2].leader_id = False
        self.assertEqual(self.Employee.crew_shift_add(self.crews[2].id, "")["error"], "no_leader")

    def test_select_switches_the_session_owner(self):
        self.Employee.crew_shift_add(self.crew_a.id, "4321")
        self.Employee.crew_shift_add(self.crew_b.id, "1111")
        self.assertEqual(self.session["session_owner"], self.leader_b.id)
        self.Employee.crew_shift_select(self.crew_a.id)
        self.assertEqual(self.session["session_owner"], self.leader_a.id)
        self.assertEqual(len(self.Employee.crew_shift_state()["crews"]), 2)

    def test_start_and_stop_are_for_the_selected_crew(self):
        self.Employee.crew_shift_add(self.crew_a.id, "4321")
        self.Employee.crew_shift_add(self.crew_b.id, "1111")
        self.Employee.crew_shift_select(self.crew_a.id)
        wo = self._workorder()
        wo.start_employee(self.leader_a.id)
        wo.crew_shift_start()
        running = wo.time_ids.filtered(lambda t: not t.date_end).employee_id
        self.assertEqual(running, self.members[self.crew_a])
        wo.crew_shift_stop()
        self.assertFalse(wo.time_ids.filtered(lambda t: not t.date_end))

    def test_kick_selected_or_everyone(self):
        self.Employee.crew_shift_add(self.crew_a.id, "4321")
        self.Employee.crew_shift_add(self.crew_b.id, "1111")
        wo = self._workorder()
        for person in self.members[self.crew_a] | self.members[self.crew_b]:
            wo.start_employee(person.id)
        self.Employee.crew_shift_select(self.crew_b.id)
        self.Employee.crew_shift_kick("selected")
        running = wo.time_ids.filtered(lambda t: not t.date_end).employee_id
        self.assertEqual(running, self.members[self.crew_a])
        self.Employee.crew_shift_kick("all")
        self.assertFalse(wo.time_ids.filtered(lambda t: not t.date_end))
        # остават в списъка
        self.assertEqual(len(self.Employee.crew_shift_state()["crews"]), 2)

    def test_remove_crew_with_or_without_leaving(self):
        self.Employee.crew_shift_add(self.crew_a.id, "4321")
        wo = self._workorder()
        wo.start_employee(self.leader_a.id)
        self.Employee.crew_shift_remove([self.crew_a.id], True)
        self.assertFalse(self.Employee.crew_shift_state()["crews"])
        self.assertFalse(wo.time_ids.filtered(lambda t: not t.date_end))

    def test_the_people_on_the_order_keep_their_own_time(self):
        """Стартирана поръчка: блок с отчетено време от хора НЕ се дели — всеки си
        получава своето време (стандартът, Росен 16.10.2026)."""
        self.rotation._crew_generate(ANCHOR, ANCHOR)
        wo = self._workorder()
        loss = self.env["mrp.workcenter.productivity.loss"].search([("loss_type", "=", "productive")], limit=1)
        start = datetime(2026, 11, 1, 6, 0)
        for employee in (self.leader_a, self.substitute):
            self.env["mrp.workcenter.productivity"].create({
                "workorder_id": wo.id, "workcenter_id": self.extruder.id, "loss_id": loss.id,
                "employee_id": employee.id, "date_start": start, "date_end": start + timedelta(hours=2)})
        blocks = wo._crew_split_blocks(start, start + timedelta(hours=2))
        index = next(i for i, b in enumerate(blocks) if b["start_utc"] <= start < b["stop_utc"])
        crews = wo._crew_split_crews(blocks, {index})
        self.assertFalse(crews[index])
        lines_before = wo.time_ids.mapped(lambda t: (t.employee_id.id, t.date_start, t.date_end))
        wo._crew_split_time()
        self.assertEqual(sorted(wo.time_ids.mapped(lambda t: (t.employee_id.id, t.date_start, t.date_end))),
                         sorted(lines_before))

    def test_without_people_the_roster_splits(self):
        self.rotation._crew_generate(ANCHOR, ANCHOR)
        wo = self._workorder()
        start = datetime(2026, 11, 1, 6, 0)
        blocks = wo._crew_split_blocks(start, start + timedelta(hours=2))
        index = next(i for i, b in enumerate(blocks) if b["start_utc"] <= start < b["stop_utc"])
        roster = self._rosters(ANCHOR).filtered(lambda r: r.shift_key == "07:00").employee_ids
        self.assertEqual(wo._crew_split_crews(blocks, {index})[index], roster.sorted("id"))

    # ------------------------------------------------------------------
    # Групите (Росен 16.10.2026)
    # ------------------------------------------------------------------

    def _groups_ready(self):
        self.Employee.crew_shift_add(self.crew_a.id, "4321")
        people = self.members[self.crew_a]
        return people

    def test_groups_need_a_crew_leader_pin(self):
        people = self._groups_ready()
        groups = [people[:1].ids, people[1:].ids]
        self.assertEqual(self.Employee.crew_shift_groups_save(self.leader_a.id, "0000", groups)["error"], "pin")
        worker = people - self.leader_a
        self.assertEqual(self.Employee.crew_shift_groups_save(worker[:1].id, "", groups)["error"], "no_leader")
        res = self.Employee.crew_shift_groups_save(self.leader_a.id, "4321", groups)
        self.assertEqual(res["groups"], 2)
        state = self.Employee.crew_shift_state()
        self.assertEqual(state["mode"], "group")
        self.assertEqual([g["employee_ids"] for g in state["groups"]], groups)

    def test_one_person_one_group(self):
        people = self._groups_ready()
        self.Employee.crew_shift_groups_save(self.leader_a.id, "4321", [people.ids, people.ids])
        groups = self.Employee.crew_shift_state()["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["employee_ids"], people.ids)

    def test_start_stop_and_kick_are_for_the_selected_group(self):
        people = self._groups_ready()
        first, second = people[:1], people[1:]
        self.Employee.crew_shift_groups_save(self.leader_a.id, "4321", [first.ids, second.ids])
        groups = self.Employee.crew_shift_state()["groups"]
        self.Employee.crew_shift_select_group(groups[1]["id"])
        wo = self._workorder()
        wo.start_employee(first.id)
        wo.crew_shift_start()
        running = wo.time_ids.filtered(lambda t: not t.date_end).employee_id
        self.assertEqual(running, people)
        self.Employee.crew_shift_kick("selected")
        running = wo.time_ids.filtered(lambda t: not t.date_end).employee_id
        self.assertEqual(running, first)
        self.Employee.crew_shift_select_group(groups[0]["id"])
        wo.crew_shift_stop()
        self.assertFalse(wo.time_ids.filtered(lambda t: not t.date_end))

    def test_remove_one_group_keeps_the_names(self):
        people = self._groups_ready()
        first, rest = people[:1], people[1:]
        self.Employee.crew_shift_groups_save(self.leader_a.id, "4321", [first.ids, rest.ids])
        groups = self.Employee.crew_shift_state()["groups"]
        # махането от списъка праща останалите групи с имената им — „Group 2“ не става „Group 1“
        kept = [{"name": g["name"], "employee_ids": g["employee_ids"]} for g in groups if g["id"] != groups[0]["id"]]
        self.Employee.crew_shift_groups_save(self.leader_a.id, "4321", kept)
        state = self.Employee.crew_shift_state()["groups"]
        self.assertEqual([g["name"] for g in state], [groups[1]["name"]])
        self.assertEqual([g["employee_ids"] for g in state], [rest.ids])

    def test_clear_all_groups(self):
        people = self._groups_ready()
        self.Employee.crew_shift_groups_save(self.leader_a.id, "4321", [people[:1].ids, people[1:].ids])
        res = self.Employee.crew_shift_groups_save(self.leader_a.id, "4321", [])
        self.assertEqual(res["groups"], 0)
        self.assertFalse(self.Employee.crew_shift_state()["groups"])
