# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Shop Floor: „Човеци“ и „Смяна/Бригада“ (Росен 15.10.2026).

- „Смяна/Бригада“: в списъка са БРИГАДИТЕ на смяната, не хората. „Редактиране на
  бригади“ ги добавя (с ПИН на бригадира) и маха (с въпрос „Да напусне ли всички
  поръчки?“). Избира се бригада, както се избира човек; старт/стоп върху поръчка е за
  хората на ИЗБРАНАТА бригада.
- „Изритай“ (и в двата режима): избраните или всички спират работа по поръчките —
  остават в списъка.
- „Групи“: бригадир (с ПИН) дели хората от списъка на групи — всеки човек в една група,
  само за текущата смяна; с група се работи като с бригада.
- Времето на стартирана поръчка: всеки човек получава СВОЕТО реално време (стандартът
  на EE, Росен 16.10.2026) — без делене поравно; планирането остава по наряда.

Сесията пази: режима, бригадите на смяната и избраната; свързаните служители на EE
(EMPLOYEES_CONNECTED) са хората на тези бригади, главният (SESSION_OWNER) — бригадирът
на избраната.
"""
from odoo import api, fields, models
from odoo.http import request

from odoo.addons.mrp_workcenter_crew_roster.models.mrp_workorder_crew_split import (
    CREW_SPLIT_LOSS_TYPES,
)
from odoo.addons.mrp_workorder.models.hr_employee import EMPLOYEES_CONNECTED, SESSION_OWNER

CREW_SHIFT_MODE = "crew_shift_mode"
CREW_SHIFT_CREWS = "crew_shift_crew_ids"
CREW_SHIFT_SELECTED = "crew_shift_selected"
CREW_SHIFT_GROUPS = "crew_shift_groups"
CREW_SHIFT_GROUP_SELECTED = "crew_shift_group_selected"
CREW_SHIFT_MODES = ("people", "crew", "group")


class PlanningCrew(models.Model):
    _inherit = "planning.crew"

    leader_id = fields.Many2one(
        "hr.employee", string="Crew Leader",
        help="Adds the crew to the shift in the Shop Floor with their PIN.")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # ------------------------------------------------------------------
    # Сесията (в тестовете — речник от контекста)
    # ------------------------------------------------------------------

    def _crew_shift_session(self):
        if request:
            return request.session
        return self.env.context.get("crew_shift_test_session", {})

    def _crew_shift_crews_on_shift(self):
        session = self._crew_shift_session()
        crews = self.env["planning.crew"].sudo().browse(session.get(CREW_SHIFT_CREWS, [])).exists()
        return crews

    @api.model
    def _crew_shift_members(self, crews):
        employees = self.sudo().search([("crew_id", "in", crews.ids)])
        result = {}
        for employee in employees:
            result.setdefault(employee.crew_id.id, []).append(employee.id)
        return result

    def _crew_shift_sync(self, crews, selected=False):
        """Записва бригадите на смяната и избраната; свързаните = хората им."""
        session = self._crew_shift_session()
        members = self._crew_shift_members(crews)
        selected = selected if selected in crews else crews[:1]
        ids = []
        if selected and selected.leader_id:
            ids.append(selected.leader_id.id)
        for crew in crews:
            if crew.leader_id:
                ids.append(crew.leader_id.id)
            ids += members.get(crew.id, [])
        session[CREW_SHIFT_CREWS] = crews.ids
        session[CREW_SHIFT_SELECTED] = selected.id or False
        session[EMPLOYEES_CONNECTED] = list(dict.fromkeys(ids))
        session[SESSION_OWNER] = selected.leader_id.id or False

    # ------------------------------------------------------------------
    # Режимът и състоянието за панела
    # ------------------------------------------------------------------

    @api.model
    def crew_shift_get_mode(self):
        return self._crew_shift_session().get(CREW_SHIFT_MODE) or "people"

    @api.model
    def crew_shift_set_mode(self, mode):
        mode = mode if mode in CREW_SHIFT_MODES else "people"
        self._crew_shift_session()[CREW_SHIFT_MODE] = mode
        return mode

    @api.model
    def crew_shift_leaders(self):
        """Бригадирите — за етикета „Бригадир“ в списъка на хората."""
        crews = self.env["planning.crew"].sudo().search([
            ("leader_id", "!=", False), ("company_id", "in", self.env.companies.ids)])
        return {crew.leader_id.id: crew.display_name for crew in crews}

    @api.model
    def crew_shift_crews(self):
        """Всички бригади за „Редактиране на бригади“."""
        crews = self.env["planning.crew"].sudo().search([
            ("rotation_id.state", "=", "approved"),
            ("company_id", "in", self.env.companies.ids),
        ])
        members = self._crew_shift_members(crews)
        on_shift = self._crew_shift_crews_on_shift()
        return [{
            "id": crew.id,
            "name": crew.display_name,
            "leader_id": crew.leader_id.id or False,
            "leader_name": crew.leader_id.name or "",
            "members": len(members.get(crew.id, [])),
            "on_shift": crew in on_shift,
        } for crew in crews.sorted(lambda c: (c.rotation_id.sequence, c.rotation_id.id, c.offset_days, c.id))]

    @api.model
    def _crew_shift_working(self, employee_ids):
        """Хората с поръчките им в ход и центровете на тези поръчки.

        В 19 `get_employees_wo_by_employees` връща и `workcenters`; в 18 — само
        `workorder`, затова центровете се вадят от поръчките (без повторения)."""
        employees = self.get_employees_wo_by_employees(employee_ids)
        wo_ids = {wo["id"] for emp in employees for wo in emp.get("workorder", [])}
        centers = {wo.id: wo.workcenter_id for wo in self.env["mrp.workorder"].browse(list(wo_ids))}
        for emp in employees:
            seen = {}
            for wo in emp.get("workorder", []):
                wc = centers.get(wo["id"])
                if wc and wc.id not in seen:
                    seen[wc.id] = {"id": wc.id, "name": wc.name}
            emp.setdefault("workcenters", list(seen.values()))
        return employees

    @api.model
    def crew_shift_state(self):
        """Бригадите на смяната за панела: хората, кой работи и къде."""
        session = self._crew_shift_session()
        crews = self._crew_shift_crews_on_shift()
        members = self._crew_shift_members(crews)
        all_ids = [i for ids in members.values() for i in ids] + crews.leader_id.ids
        working = {e["id"]: e for e in self._crew_shift_working(list(set(all_ids)))}
        result = []
        for crew in crews:
            ids = list(dict.fromkeys(crew.leader_id.ids + members.get(crew.id, [])))
            workcenters = {}
            for employee_id in ids:
                for wc in working.get(employee_id, {}).get("workcenters", []):
                    entry = workcenters.setdefault(wc["id"], {"id": wc["id"], "name": wc["name"], "people": 0})
                    entry["people"] += 1
            result.append({
                "id": crew.id,
                "name": crew.display_name,
                "leader_id": crew.leader_id.id or False,
                "leader_name": crew.leader_id.name or "",
                "members": len(ids),
                "working": sum(1 for i in ids if working.get(i, {}).get("workcenters")),
                "workcenters": list(workcenters.values()),
            })
        return {"mode": session.get(CREW_SHIFT_MODE) or "people",
                "selected": session.get(CREW_SHIFT_SELECTED) or False,
                "crews": result,
                "groups": self._crew_shift_groups_state(),
                "group_selected": session.get(CREW_SHIFT_GROUP_SELECTED) or False}

    # ------------------------------------------------------------------
    # Групите (Росен 16.10.2026)
    # ------------------------------------------------------------------

    def _crew_shift_groups(self):
        """Групите на смяната — само свързаните хора, всеки в една група."""
        session = self._crew_shift_session()
        connected = set(session.get(EMPLOYEES_CONNECTED, []))
        groups, seen = [], set()
        for group in session.get(CREW_SHIFT_GROUPS, []) or []:
            ids = [i for i in group.get("employee_ids", []) if i in connected and i not in seen]
            seen.update(ids)
            groups.append({"id": group["id"], "name": group["name"], "employee_ids": ids})
        return groups

    def _crew_shift_groups_state(self):
        groups = self._crew_shift_groups()
        all_ids = list({i for g in groups for i in g["employee_ids"]})
        working = {e["id"]: e for e in self._crew_shift_working(all_ids)}
        names = {e.id: e.name for e in self.sudo().browse(all_ids)}
        result = []
        for group in groups:
            workcenters = {}
            for employee_id in group["employee_ids"]:
                for wc in working.get(employee_id, {}).get("workcenters", []):
                    entry = workcenters.setdefault(wc["id"], {"id": wc["id"], "name": wc["name"], "people": 0})
                    entry["people"] += 1
            result.append({
                "id": group["id"], "name": group["name"],
                "employee_ids": group["employee_ids"],
                "names": [names[i] for i in group["employee_ids"]],
                "members": len(group["employee_ids"]),
                "working": sum(1 for i in group["employee_ids"] if working.get(i, {}).get("workcenters")),
                "workcenters": list(workcenters.values()),
            })
        return result

    @api.model
    def crew_shift_group_leaders(self):
        """Бригадирите, които могат да делят на групи: свързаните, иначе всички."""
        crews = self.env["planning.crew"].sudo().search([
            ("leader_id", "!=", False), ("company_id", "in", self.env.companies.ids)])
        leaders = crews.leader_id
        connected = set(self._crew_shift_session().get(EMPLOYEES_CONNECTED, []))
        present = leaders.filtered(lambda e: e.id in connected)
        return [{"id": e.id, "name": e.name} for e in (present or leaders)]

    @api.model
    def crew_shift_groups_save(self, leader_id, pin, groups):
        """Записва групите с ПИН-а на бригадир. `groups` = [[id на служител, ...], ...] —
        или [{"name": ..., "employee_ids": [...]}, ...], когато имената се пазят (махане на
        група от списъка); празни групи отпадат."""
        leader = self.sudo().browse(leader_id).exists()
        is_leader = leader and self.env["planning.crew"].sudo().search_count([("leader_id", "=", leader.id)])
        if not is_leader:
            return {"ok": False, "error": "no_leader"}
        if not leader.pin_validation(pin):
            return {"ok": False, "error": "pin"}
        session = self._crew_shift_session()
        connected = set(session.get(EMPLOYEES_CONNECTED, []))
        seen, saved = set(), []
        for index, group in enumerate(groups or [], start=1):
            name = group.get("name") if isinstance(group, dict) else False
            ids = group.get("employee_ids", []) if isinstance(group, dict) else group
            ids = [i for i in ids if i in connected and i not in seen]
            seen.update(ids)
            if ids:
                saved.append({"id": index, "name": name or self.env._("Group %s", index), "employee_ids": ids})
        session[CREW_SHIFT_GROUPS] = saved
        session[CREW_SHIFT_GROUP_SELECTED] = saved[0]["id"] if saved else False
        session[CREW_SHIFT_MODE] = "group"
        return {"ok": True, "groups": len(saved)}

    @api.model
    def crew_shift_select_group(self, group_id):
        if any(g["id"] == group_id for g in self._crew_shift_groups()):
            self._crew_shift_session()[CREW_SHIFT_GROUP_SELECTED] = group_id
            return True
        return False

    @api.model
    def _crew_shift_group_people(self, scope="selected"):
        session = self._crew_shift_session()
        groups = self._crew_shift_groups()
        if scope != "all":
            groups = [g for g in groups if g["id"] == session.get(CREW_SHIFT_GROUP_SELECTED)]
        return self.sudo().browse([i for g in groups for i in g["employee_ids"]])

    # ------------------------------------------------------------------
    # Действията от панела
    # ------------------------------------------------------------------

    @api.model
    def crew_shift_add(self, crew_id, pin=False):
        """Добавя бригадата към смяната с ПИН-а на бригадира ѝ и я избира."""
        crew = self.env["planning.crew"].sudo().browse(crew_id).exists()
        if not crew:
            return {"ok": False, "error": "no_crew"}
        if not crew.leader_id:
            return {"ok": False, "error": "no_leader"}
        if not crew.leader_id.pin_validation(pin):
            return {"ok": False, "error": "pin"}
        self._crew_shift_sync(self._crew_shift_crews_on_shift() | crew, crew)
        self._crew_shift_session()[CREW_SHIFT_MODE] = "crew"
        return {"ok": True}

    @api.model
    def crew_shift_remove(self, crew_ids, leave_orders=False):
        """Маха бригадите от смяната; `leave_orders` — хората им спират работа навсякъде."""
        crews = self.env["planning.crew"].sudo().browse(crew_ids).exists()
        if leave_orders:
            self._crew_shift_people(crews).stop_all_workorder_from_employee()
        session = self._crew_shift_session()
        selected = self.env["planning.crew"].sudo().browse(session.get(CREW_SHIFT_SELECTED) or [])
        self._crew_shift_sync(self._crew_shift_crews_on_shift() - crews, selected)
        return True

    @api.model
    def crew_shift_select(self, crew_id):
        """Избира бригада от смяната (ПИН-ът е даден при добавянето)."""
        crew = self.env["planning.crew"].sudo().browse(crew_id).exists()
        crews = self._crew_shift_crews_on_shift()
        if crew not in crews:
            return False
        self._crew_shift_sync(crews, crew)
        return True

    @api.model
    def _crew_shift_people(self, crews):
        members = self._crew_shift_members(crews)
        ids = crews.leader_id.ids + [i for ids in members.values() for i in ids]
        return self.sudo().browse(list(dict.fromkeys(ids)))

    @api.model
    def crew_shift_kick(self, scope="selected"):
        """„Изритай“: избраните или всички в списъка спират работа по поръчките.
        В режим „Смяна/Бригада“ избраната е бригада; в „Човеци“ — главният служител."""
        session = self._crew_shift_session()
        if session.get(CREW_SHIFT_MODE) == "group":
            people = self._crew_shift_group_people(scope)
        elif session.get(CREW_SHIFT_MODE) == "crew":
            crews = self._crew_shift_crews_on_shift()
            if scope != "all":
                crews = crews.filtered(lambda c: c.id == session.get(CREW_SHIFT_SELECTED))
            people = self._crew_shift_people(crews)
        elif scope == "all":
            people = self.sudo().browse(session.get(EMPLOYEES_CONNECTED, [])).exists()
        else:
            people = self.sudo().browse(session.get(SESSION_OWNER) or []).exists()
        people.stop_all_workorder_from_employee()
        return len(people)


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    def _crew_shift_selected_people(self):
        Employee = self.env["hr.employee"]
        session = Employee._crew_shift_session()
        if session.get(CREW_SHIFT_MODE) == "group":
            return Employee._crew_shift_group_people("selected")
        crew = self.env["planning.crew"].sudo().browse(session.get(CREW_SHIFT_SELECTED) or []).exists()
        return Employee._crew_shift_people(crew)

    def crew_shift_start(self):
        """Режим „Смяна/Бригада“: хората на избраната бригада започват работа."""
        self.ensure_one()
        people = self._crew_shift_selected_people()
        if not people:
            return False
        if self.state not in ("progress", "done", "cancel"):
            self.with_context(mrp_display=True).button_start()
        for employee in people:
            if self.allowed_employees and employee not in self.allowed_employees and not self.all_employees_allowed:
                continue
            self.start_employee(employee.id)
        return True

    def crew_shift_stop(self):
        """Режим „Смяна/Бригада“: хората на избраната бригада спират работа."""
        self.ensure_one()
        people = self._crew_shift_selected_people() & self.employee_ids
        if people:
            self.stop_employee(people.ids)
        return True

    def _crew_split_crews(self, blocks, indexes):
        """Блок с отчетено време от хора (Shop Floor) НЕ се дели — всеки човек си получава
        своето реално време (стандартът на EE, Росен 16.10.2026); без отчетени хора —
        нарядът. Празен екип за блока = редовете остават, както са отчетени."""
        crews = super()._crew_split_crews(blocks, indexes)
        if not self.workcenter_id.crew_rotation_id:
            # само центровете по ротация; другите делят по наряда, както досега
            return crews
        lines = self.sudo().time_ids.filtered(
            lambda t: t.employee_id and t.date_start and t.date_end
            and t.loss_type in CREW_SPLIT_LOSS_TYPES)
        for index in indexes:
            block = blocks[index]
            present = lines.filtered(
                lambda t: t.date_start < block["stop_utc"] and t.date_end > block["start_utc"]
            ).employee_id
            if present:
                crews[index] = self.env["hr.employee"]
        return crews
