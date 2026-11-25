# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import clean_context

from ..models.mrp_workcenter_replan_batch import CREW_REPLAN_PERIOD_DAYS


class MrpWorkcenterReplanWizard(models.TransientModel):
    """„Rearrange Plan“ (фаза 2, SPEC Р39, TECH_DESIGN §2 и §9.13.3):
    входните данни на двигателя M6 и пускането му със source='wizard'.

    Подразбиращите се стойности идват от ключовете `crew_workcenter_ids`,
    `crew_date_from`, `crew_date_to` в контекста, НЕ от `default_*` (Ф3):
    двигателят създава `resource.calendar.leaves` с полета `date_from` /
    `date_to`, и префиксът би изтекъл точно там.
    """

    _name = "mrp.workcenter.replan.wizard"
    _description = "Rearrange Work Center Plan"

    @api.model
    def _crew_default_date_from(self):
        """Началото на периода: `crew_date_from` от контекста, но не преди
        днес (обхватът на Ганта почва от предишния период)."""
        today = fields.Date.context_today(self)
        start = fields.Date.to_date(self.env.context.get("crew_date_from"))
        return max(today, start) if start else today

    @api.model
    def _crew_default_date_to(self):
        """Краят: `crew_date_to`, ако не е преди началото, иначе началото
        + CREW_REPLAN_PERIOD_DAYS."""
        start = self._crew_default_date_from()
        stop = fields.Date.to_date(self.env.context.get("crew_date_to"))
        if stop and stop >= start:
            return stop
        return start + timedelta(days=CREW_REPLAN_PERIOD_DAYS)

    @api.model
    def _crew_default_workcenters(self):
        """Центровете от `crew_workcenter_ids` (Гантът подава своя)."""
        ids = self.env.context.get("crew_workcenter_ids") or []
        return self.env["mrp.workcenter"].browse(ids).exists()

    workcenter_ids = fields.Many2many(
        "mrp.workcenter",
        "mrp_workcenter_replan_wizard_workcenter_rel",
        "wizard_id",
        "workcenter_id",
        string="Work Centers",
        required=True,
        default=_crew_default_workcenters,
        domain="[('company_id', 'in', allowed_company_ids)]",
        help="The work centers whose not started work orders are replanned.",
    )
    date_from = fields.Date(
        string="From",
        required=True,
        default=_crew_default_date_from,
        help="The first day of the period. It cannot be before today. Not started "
        "work orders planned between now and this day keep their places.",
    )
    date_to = fields.Date(
        string="To",
        required=True,
        default=_crew_default_date_to,
        help="The last day of the period (included).",
    )
    scope = fields.Selection(
        [("not_started", "Not Started"), ("late", "Late")],
        required=True,
        default="not_started",
        help="Not Started: all work orders that have not started yet. Late: "
        "only the not started work orders that are late. Started work orders "
        "are never moved.",
    )
    priority_key = fields.Selection(
        [
            ("deadline", "Deadline"),
            ("mo_priority", "Manufacturing Order Priority"),
            ("partner", "Customer"),
            ("create_date", "Creation Date"),
        ],
        string="Order By",
        required=True,
        default="deadline",
        help="The order in which the work orders get their new places. A work "
        "order always comes after the work orders it depends on.",
    )
    partner_line_ids = fields.One2many(
        "mrp.workcenter.replan.wizard.partner",
        "wizard_id",
        string="Customer Order",
        help="The customers in the order of their priority. Customers not in "
        "the list come after them, work orders without a customer come last.",
    )
    partner_filter_ids = fields.Many2many(
        "res.partner",
        "mrp_workcenter_replan_wizard_partner_filter_rel",
        "wizard_id",
        "partner_id",
        string="Only Customers",
        help="Replan only the work orders of these customers. Empty means all "
        "customers.",
    )
    respect_roster = fields.Boolean(
        string="Respect Crew Rosters",
        default=True,
        help="Plan only in the shifts that have a crew roster. A work center "
        "without any crew roster in the period stays open.",
    )
    use_alternatives = fields.Boolean(
        string="Use Alternative Work Centers",
        default=False,
        help="Allow moving a work order to one of its alternative work "
        "centers. The alternative work centers must be among the selected "
        "ones.",
    )

    def _crew_params(self):
        """Входните данни на двигателя (M6, `_crew_default_params`)."""
        self.ensure_one()
        lines = self.partner_line_ids.sorted(lambda line: (line.sequence, line.id))
        return {
            "workcenter_ids": self.workcenter_ids.ids,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "scope": self.scope,
            "priority_key": self.priority_key,
            "partner_ids": lines.partner_id.ids,
            "partner_filter_ids": self.partner_filter_ids.ids,
            "respect_roster": self.respect_roster,
            "use_alternatives": self.use_alternatives,
            "only_stale": False,
        }

    def action_apply(self):
        """Пуска двигателя (M6) със source='wizard'.

        1. проверки: поне един център, една фирма, начало не преди днес
           (краят преди началото — от `_crew_normalize_params`);
        2. `_crew_run` с контекст без `default_*` (Ф3);
        3. от Ганта (`crew_from_gantt`) — затваря се и връща id-то на
           партидата в `infos`: Гантът сам отваря отчета и знае коя партида
           да предложи за Undo; иначе — отчетът.
        """
        self.ensure_one()
        workcenters = self.workcenter_ids
        if not workcenters:
            raise UserError(self.env._("Select at least one work center to replan."))
        if len(workcenters.company_id) > 1:
            raise UserError(self.env._("Select work centers of one company."))
        if self.date_from < fields.Date.context_today(self):
            raise UserError(self.env._("The period cannot start before today."))
        batch = (
            self.env["mrp.workcenter.replan.batch"]
            .with_context(clean_context(self.env.context))
            ._crew_run(self._crew_params(), "wizard")
        )
        if self.env.context.get("crew_from_gantt"):
            return {
                "type": "ir.actions.act_window_close",
                "infos": {"crew_batch_id": batch.id},
            }
        return batch._crew_action_open()


class MrpWorkcenterReplanWizardPartner(models.TransientModel):
    """Ред от подредбата по клиент в съветника (`priority_key='partner'`)."""

    _name = "mrp.workcenter.replan.wizard.partner"
    _description = "Rearrange Work Center Plan: Customer Order"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "mrp.workcenter.replan.wizard", required=True, ondelete="cascade"
    )
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
