# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import crew_law


class HrContract(models.Model):
    # В 18 няма hr.version — назначенията и нощният труд са в договора (Росен 07.11.2026)
    _inherit = "hr.contract"

    crew_membership_ids = fields.One2many(
        "planning.crew.membership", "contract_id", string="Crews",
        groups="hr.group_hr_user")
    # Нощен труд (чл. 140, ал. 4 и чл. 140а КТ; чл. 7 НРВПО) — Росен 15.10.2026: „добави ги“
    crew_pregnancy_from = fields.Date(
        string="Pregnancy / IVF From", groups="hr.group_hr_user", tracking=True,
        help="Pregnancy or advanced stage of in-vitro treatment: night work and "
             "overtime are forbidden (Labour Code, Art. 140 and 147).")
    crew_pregnancy_to = fields.Date(
        string="Pregnancy / IVF To", groups="hr.group_hr_user", tracking=True)
    crew_night_consent_needed = fields.Boolean(
        string="Night Work Only With Written Consent", groups="hr.group_hr_user",
        tracking=True,
        help="Mother of a child under 6 or of a child with a disability, employee with "
             "reassigned work or studying without leaving work: night work only with "
             "written consent (Labour Code, Art. 140, para. 4, items 3–5).")
    crew_night_consent_date = fields.Date(
        string="Night Work Consent Given", groups="hr.group_hr_user", tracking=True)
    crew_night_consent_revoked = fields.Date(
        string="Night Work Consent Withdrawn", groups="hr.group_hr_user", tracking=True,
        help="From this day the written consent no longer applies (Ordinance on "
             "working time, Art. 7: at least 3 days notice).")
    crew_night_medical_date = fields.Date(
        string="Night Work Medical Exam", groups="hr.group_hr_user", tracking=True,
        help="Night workers are hired only after a medical exam (Labour Code, Art. 140a).")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # В 19 служителят наследява версията на договора (_inherits) и вижда полетата ѝ;
    # в 18 — свързани полета към текущия договор, за да остане картонът същият.
    crew_membership_ids = fields.One2many(
        related="contract_id.crew_membership_ids", readonly=False, groups="hr.group_hr_user")
    crew_pregnancy_from = fields.Date(
        related="contract_id.crew_pregnancy_from", readonly=False, groups="hr.group_hr_user")
    crew_pregnancy_to = fields.Date(
        related="contract_id.crew_pregnancy_to", readonly=False, groups="hr.group_hr_user")
    crew_night_consent_needed = fields.Boolean(
        related="contract_id.crew_night_consent_needed", readonly=False, groups="hr.group_hr_user")
    crew_night_consent_date = fields.Date(
        related="contract_id.crew_night_consent_date", readonly=False, groups="hr.group_hr_user")
    crew_night_consent_revoked = fields.Date(
        related="contract_id.crew_night_consent_revoked", readonly=False, groups="hr.group_hr_user")
    crew_night_medical_date = fields.Date(
        related="contract_id.crew_night_medical_date", readonly=False, groups="hr.group_hr_user")
    crew_membership_all_ids = fields.One2many(
        "planning.crew.membership", "employee_id", string="Crew History",
        groups="hr.group_hr_user")
    # Съхранено, за да се търси и групира в списъка (Росен 14.10.2026);
    # денят се сменя с крона `_cron_crew_refresh`.
    crew_id = fields.Many2one(
        "planning.crew", string="Crew", compute="_compute_crew_id",
        inverse="_inverse_crew_id", store=True, readonly=False, index=True,
        groups="hr.group_hr_user",
        help="The crew of the employee today. Changing it closes the current "
             "crew membership yesterday and opens a new one from today.")
    crew_substitute_ids = fields.Many2many(
        "hr.employee", "hr_employee_crew_substitute_rel", "employee_id", "substitute_id",
        string="Crew Substitutes", groups="hr.group_hr_user",
        help="Who takes the shifts of this employee during an approved leave, "
             "in this order; the first one who is free gets the shift.")

    def _crew_today(self):
        """Денят на назначението: контекстът `crew_date` (импорт с дата от
        началото на цикъла) или днес."""
        return fields.Date.to_date(self.env.context.get("crew_date")) or \
            fields.Date.context_today(self)

    @api.depends("crew_membership_all_ids.crew_id", "crew_membership_all_ids.date_from",
                 "crew_membership_all_ids.date_to")
    def _compute_crew_id(self):
        today = fields.Date.context_today(self)
        for employee in self:
            current = employee.sudo().crew_membership_all_ids.filtered(
                lambda m: m.date_from <= today and (not m.date_to or m.date_to >= today))
            employee.crew_id = current[:1].crew_id

    def _inverse_crew_id(self):
        """Смяната на бригадата в картона = ново назначение от днес; текущото
        се затваря вчера (или се поправя, ако е започнало днес)."""
        Membership = self.env["planning.crew.membership"].sudo()
        for employee in self:
            day = employee._crew_today()
            current = employee.sudo().crew_membership_all_ids.filtered(
                lambda m: m.date_from <= day and (not m.date_to or m.date_to >= day))
            if current.crew_id == employee.crew_id:
                continue
            same_day = current.filtered(lambda m: m.date_from == day)
            if employee.crew_id and same_day:
                same_day[:1].crew_id = employee.crew_id
                (current - same_day[:1]).date_to = day - timedelta(days=1)
                continue
            same_day.unlink()
            (current - same_day).date_to = day - timedelta(days=1)
            if employee.crew_id:
                if not employee.contract_id:
                    # в 18 назначението стои в договора — без текущ договор няма къде
                    raise UserError(self.env._(
                        "%s has no running contract: the crew is kept in the contract.",
                        employee.name))
                Membership.create({
                    "contract_id": employee.contract_id.id,
                    "crew_id": employee.crew_id.id,
                    "date_from": day,
                })

    def _crew_night_issues(self, day):
        """Защо служителят не бива да работи нощем в деня `day` (кодове):
        minor, pregnancy, no_consent, no_medical. Празно — може."""
        self.ensure_one()
        emp = self.sudo()
        ver = emp.contract_id
        issues = []
        age = crew_law.age_on(emp.birthday, day)
        if age is not None and age < crew_law.ADULT_AGE:
            issues.append("minor")
        if ver.crew_pregnancy_from and ver.crew_pregnancy_from <= day and (
                not ver.crew_pregnancy_to or ver.crew_pregnancy_to >= day):
            issues.append("pregnancy")
        # учащият — от локализацията, ако е инсталирана; трудоустроеният се отбелязва на
        # ръка: решение на ТЕЛК само по себе си НЕ е трудоустрояване (чл. 140, ал. 4, т. 4)
        studying = "l10n_bg_nap_is_part_time_student" in ver._fields and ver.l10n_bg_nap_is_part_time_student
        if ver.crew_night_consent_needed or studying:
            consent = ver.crew_night_consent_date and ver.crew_night_consent_date <= day and (
                not ver.crew_night_consent_revoked or ver.crew_night_consent_revoked > day)
            if not consent:
                issues.append("no_consent")
        if not ver.crew_night_medical_date or ver.crew_night_medical_date > day:
            issues.append("no_medical")
        return issues

    @api.model
    def _cron_crew_refresh(self):
        """Назначенията, които започват днес или са свършили вчера, сменят
        бригадата в картона."""
        today = fields.Date.context_today(self)
        memberships = self.env["planning.crew.membership"].sudo().search([
            "|", ("date_from", "=", today),
            ("date_to", "=", today - timedelta(days=1)),
        ])
        memberships.employee_id._compute_crew_id()
