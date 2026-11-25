# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
import inspect
from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time
from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged

from .common import MONDAY, CrewWorkorderCommon

FRIDAY = MONDAY - timedelta(days=3)
SUNDAY = MONDAY - timedelta(days=1)
TUESDAY = MONDAY + timedelta(days=1)
WEDNESDAY = MONDAY + timedelta(days=2)
# 05.10.2026 11:00 в София (UTC+3) — „сега“, както в test_replan.
FROZEN_NOW = "2026-10-05 08:00:00"


@tagged("post_install", "-at_install", "crew_roster")
@freeze_time(FROZEN_NOW)
class TestReplanWizard(CrewWorkorderCommon):
    """Тестове 31–33 от TECH_DESIGN §9.13.6: съветникът „Rearrange Plan“,
    Undo от отчета (`crew_can_undo`, `action_undo_report`) и отпадането на
    M9 („Automatic“)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Batch = cls.env["mrp.workcenter.replan.batch"]
        cls.Wizard = cls.env["mrp.workcenter.replan.wizard"]
        cls.wc_alt = cls._make_workcenter("WC Alternative", cls.cal_pg)
        cls.crew12 = cls.emp1 | cls.emp2
        cls.mrp_user = new_test_user(
            cls.env,
            login="crew_wizard_user",
            email="crew_wizard_user@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.mrp_user2 = new_test_user(
            cls.env,
            login="crew_wizard_user2",
            email="crew_wizard_user2@crew-test.invalid",
            groups="mrp.group_mrp_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.manager = new_test_user(
            cls.env,
            login="crew_wizard_manager",
            email="crew_wizard_manager@crew-test.invalid",
            groups="mrp.group_mrp_manager",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )

    # --- помощни ---------------------------------------------------------

    def _mo(self, deadline=None):
        mo = self.env["mrp.production"].create(
            {
                "product_id": self.product.id,
                "product_qty": 1.0,
                "date_deadline": deadline,
            }
        )
        mo.action_confirm()
        return mo

    def _stale(self, mo=None, workcenter=None, **extra):
        """Незапочната поръчка в миналото (петък 09:00–10:00)."""
        return self._make_wo(
            workcenter or self.wc_pg,
            self._utc(FRIDAY, 9),
            mo=mo or self._mo(),
            overlap=True,
            **extra,
        )

    def _time_line(self, wo, start, end):
        loss = self.env["mrp.workcenter.productivity.loss"].search(
            [("loss_type", "=", "productive")], limit=1
        )
        return self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": wo.id,
                "workcenter_id": wo.workcenter_id.id,
                "loss_id": loss.id,
                "employee_id": self.emp3.id,
                "date_start": start,
                "date_end": end,
            }
        )

    def _wizard(self, context=None, user=None, **vals):
        Wizard = self.Wizard.with_user(user) if user else self.Wizard
        if context:
            Wizard = Wizard.with_context(**context)
        values = {"workcenter_ids": [Command.set(self.wc_pg.ids)]}
        values.update(vals)
        return Wizard.create(values)

    def _apply(self, wizard):
        """Пуска съветника и връща новата партида."""
        action = wizard.action_apply()
        if action["type"] == "ir.actions.act_window_close":
            return self.Batch.browse(action["infos"]["crew_batch_id"])
        return self.Batch.browse(action["res_id"])

    def _plan(self, wo):
        return (wo.workcenter_id, wo.date_start, wo.date_finished, wo.crew_lane)

    def _line(self, batch, wo):
        return batch.line_ids.filtered(lambda line: line.workorder_id == wo)

    # --- 31. Съветникът -------------------------------------------------------

    def test_31_1_defaults_from_crew_keys(self):
        """31.1: подразбиращите се от `crew_*`; без контекст — днес…+14;
        минало `crew_date_from` → днес; изрично минала дата → UserError."""
        wizard = self.Wizard.with_context(
            crew_workcenter_ids=[self.wc_pg.id],
            crew_date_from=TUESDAY,
            crew_date_to=TUESDAY + timedelta(days=4),
        ).new({})
        self.assertEqual(wizard.workcenter_ids._origin, self.wc_pg)
        self.assertEqual(
            (wizard.date_from, wizard.date_to), (TUESDAY, TUESDAY + timedelta(days=4))
        )
        wizard = self.Wizard.new({})
        self.assertFalse(wizard.workcenter_ids)
        self.assertEqual(
            (wizard.date_from, wizard.date_to), (MONDAY, MONDAY + timedelta(days=14))
        )
        self.assertEqual(
            (wizard.scope, wizard.priority_key, wizard.respect_roster, wizard.use_alternatives),
            ("not_started", "deadline", True, False),
        )
        # Обхватът на Ганта почва от предишния период: началото → днес.
        wizard = self.Wizard.with_context(
            crew_date_from=MONDAY - timedelta(days=7),
            crew_date_to=MONDAY + timedelta(days=3),
        ).new({})
        self.assertEqual(
            (wizard.date_from, wizard.date_to), (MONDAY, MONDAY + timedelta(days=3))
        )
        # Целият период в миналото: краят — днес + 14.
        wizard = self.Wizard.with_context(
            crew_date_from=MONDAY - timedelta(days=10),
            crew_date_to=MONDAY - timedelta(days=8),
        ).new({})
        self.assertEqual(
            (wizard.date_from, wizard.date_to), (MONDAY, MONDAY + timedelta(days=14))
        )
        wo = self._stale()
        wizard = self._wizard(date_from=SUNDAY, date_to=TUESDAY)
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertFalse(self.Batch.search([]).filtered(lambda b: wo in b.line_ids.workorder_id))
        wizard = self._wizard(date_from=TUESDAY, date_to=MONDAY)
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_31_2_no_default_keys(self):
        """31.2 (Ф3): действието е без контекст; двигателят не вижда
        `default_*`, дори да са подадени."""
        action = self.env.ref("mrp_workcenter_crew_roster.mrp_workcenter_replan_wizard_action")
        self.assertIn(action.context, (False, "{}"))
        wo = self._stale()
        seen = {}
        Batch = type(self.Batch)
        original = Batch._crew_run

        def spy(batch_self, params, source):
            seen.update(batch_self.env.context)
            return original(batch_self, params, source)

        context = {
            "default_workcenter_id": self.wc_alt.id,
            "default_name": "Leaked",
            "default_time_type": "leave",
            "crew_from_gantt": True,
        }
        with patch.object(Batch, "_crew_run", spy):
            batch = self._apply(self._wizard(context=context))
        self.assertTrue(seen)
        self.assertFalse([key for key in seen if key.startswith("default_")])
        self.assertTrue(seen.get("crew_from_gantt"))
        self.assertEqual(self._line(batch, wo).result, "moved")
        self.assertEqual(wo.workcenter_id, self.wc_pg)
        self.assertEqual(wo.leave_id.name, wo.display_name)
        self.assertEqual(wo.date_start, self._utc(MONDAY, 11))

    def test_31_3_params_reach_batch(self):
        """31.3: входните данни стигат до партидата 1:1 (редът на клиентите
        по `sequence`), source='wizard'."""
        Partner = self.env["res.partner"]
        p1 = Partner.create({"name": "Crew Wizard Customer 1"})
        p2 = Partner.create({"name": "Crew Wizard Customer 2"})
        p3 = Partner.create({"name": "Crew Wizard Customer 3"})
        wizard = self._wizard(
            workcenter_ids=[Command.set((self.wc_pg | self.wc_alt).ids)],
            date_from=TUESDAY,
            date_to=WEDNESDAY,
            scope="late",
            priority_key="partner",
            partner_line_ids=[
                Command.create({"sequence": 20, "partner_id": p1.id}),
                Command.create({"sequence": 5, "partner_id": p3.id}),
                Command.create({"sequence": 10, "partner_id": p2.id}),
            ],
            partner_filter_ids=[Command.set([p2.id, p1.id])],
            respect_roster=False,
            use_alternatives=True,
        )
        batch = self._apply(wizard)
        self.assertEqual(batch.source, "wizard")
        self.assertEqual(batch.user_id, self.env.user)
        self.assertEqual(batch.workcenter_ids, self.wc_pg | self.wc_alt)
        params = dict(batch.params)
        self.assertEqual(sorted(params["workcenter_ids"]), sorted((self.wc_pg | self.wc_alt).ids))
        self.assertEqual(sorted(params["partner_filter_ids"]), sorted([p1.id, p2.id]))
        del params["workcenter_ids"], params["partner_filter_ids"]
        self.assertEqual(
            params,
            {
                "date_from": "2026-10-06",
                "date_to": "2026-10-07",
                "scope": "late",
                "priority_key": "partner",
                "partner_ids": [p3.id, p2.id, p1.id],
                "respect_roster": False,
                "use_alternatives": True,
                "only_stale": False,
            },
        )

    def test_31_4_scope_and_partner_filter(self):
        """31.4: `scope='late'` и филтърът по клиент ограничават редовете."""
        Partner = self.env["res.partner"]
        p1 = Partner.create({"name": "Crew Wizard Customer 1"})
        p2 = Partner.create({"name": "Crew Wizard Customer 2"})
        late1 = self._stale(mo=self._mo(deadline=self._utc(SUNDAY, 12)))
        late2 = self._stale(mo=self._mo(deadline=self._utc(SUNDAY, 12)))
        on_time = self._stale(mo=self._mo(deadline=self._utc(WEDNESDAY, 12)))
        partners = {late1.id: p1, late2.id: p2, on_time.id: p1}
        WorkOrder = type(self.env["mrp.workorder"])
        with patch.object(
            WorkOrder, "_crew_partner", lambda wo: partners.get(wo.id, Partner)
        ):
            batch = self._apply(
                self._wizard(scope="late", partner_filter_ids=[Command.set(p1.ids)])
            )
        self.assertEqual(batch.line_ids.workorder_id, late1)
        self.assertEqual(late1.date_start, self._utc(MONDAY, 11))
        self.assertEqual(late2.date_start, self._utc(FRIDAY, 9))
        self.assertEqual(on_time.date_start, self._utc(FRIDAY, 9))

    def test_31_5_companies_and_empty(self):
        """31.5: центрове на две фирми → UserError; без центрове → UserError."""
        company2 = self.env["res.company"].create({"name": "Crew Wizard Company 2"})
        cal2 = self._make_calendar(
            "Company 2 calendar", [(0, 8, 17, "morning", "Monday")], company_id=company2.id
        )
        wc2 = self._make_workcenter("WC Company 2", cal2, company=company2)
        wo = self._stale()
        wizard = self._wizard(workcenter_ids=[Command.set((self.wc_pg | wc2).ids)])
        with self.assertRaisesRegex(UserError, "one company"):
            wizard.action_apply()
        self.assertEqual(wo.date_start, self._utc(FRIDAY, 9))
        wizard = self._wizard()
        wizard.workcenter_ids = [Command.clear()]
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_31_6_return_action(self):
        """31.6: без `crew_from_gantt` — отчетът (формата на партидата); с
        него — `act_window_close` с `infos.crew_batch_id`."""
        self._stale()
        action = self._wizard().action_apply()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(
            (action["res_model"], action["target"], action["view_mode"]),
            ("mrp.workcenter.replan.batch", "new", "form"),
        )
        batch = self.Batch.browse(action["res_id"])
        self.assertEqual(batch.source, "wizard")
        self._stale()
        action = self._wizard(context={"crew_from_gantt": True}).action_apply()
        self.assertEqual(action["type"], "ir.actions.act_window_close")
        batch2 = self.Batch.browse(action["infos"]["crew_batch_id"])
        self.assertEqual(batch2.source, "wizard")
        self.assertNotEqual(batch2, batch)
        self.assertEqual(self.Batch.search([], limit=1), batch2)
        # Публичният двойник за Ганта отваря същия отчет. Гантът го взима
        # през call_kw (без clean_action), затова `views` трябва да е в
        # самото действие — иначе doAction пада (намерено от tour-а, 8.2).
        report = batch2.action_open_report()
        self.assertEqual(report["res_id"], batch2.id)
        self.assertEqual(report["views"], [(False, "form")])
        recompute = self.env["mrp.workcenter.roster"].with_context(
            crew_workcenter_id=self.wc_pg.id
        ).action_crew_recompute()
        self.assertEqual(recompute["views"], [(False, "form")])

    def test_31_7_mrp_user_rights(self):
        """31.7: MRP User пуска съветника (ACL) и отменя своята партида;
        друг MRP User — AccessError."""
        wo = self._stale()
        old = self._plan(wo)
        # Центърът — от `crew_workcenter_ids`, както го подава Гантът; редът
        # на клиентите проверява ACL на модела за подредбата.
        wizard = (
            self.Wizard.with_user(self.mrp_user)
            .with_context(crew_workcenter_ids=self.wc_pg.ids)
            .create(
                {
                    "partner_line_ids": [
                        Command.create({"partner_id": self.mrp_user.partner_id.id})
                    ]
                }
            )
        )
        self.assertEqual(wizard.workcenter_ids, self.wc_pg)
        batch = self._apply(wizard)
        self.assertEqual(batch.user_id, self.mrp_user)
        self.assertEqual(self._line(batch, wo).result, "moved")
        self.assertFalse(batch.with_user(self.mrp_user2).crew_can_undo)
        with self.assertRaises(AccessError):
            batch.with_user(self.mrp_user2).action_undo()
        self.assertTrue(batch.with_user(self.mrp_user).crew_can_undo)
        action = batch.with_user(self.mrp_user).action_undo_report()
        self.assertEqual((action["res_id"], action["target"]), (batch.id, "new"))
        self.assertEqual(batch.state, "undone")
        self.assertEqual(self._plan(wo), old)

    def test_31_8_views_and_entry(self):
        """31.8 (§9.13.3, Ф2-4): съветникът се отваря само от Ганта (никое
        меню не сочи действието му); „Rearrange“ иска потвърждение, редът на
        клиентите се вижда само при `priority_key='partner'`; бутонът „Undo“
        на отчета вика `action_undo_report`, иска потвърждение и се крие
        без `crew_can_undo`."""
        action = self.env.ref("mrp_workcenter_crew_roster.mrp_workcenter_replan_wizard_action")
        self.assertFalse(
            self.env["ir.ui.menu"]
            .sudo()
            .with_context(active_test=False)
            .search([("action", "=", "%s,%s" % (action._name, action.id))])
        )
        self.assertEqual((action.res_model, action.target), (self.Wizard._name, "new"))
        arch = etree.fromstring(self.Wizard.get_view(view_type="form")["arch"])
        [apply] = arch.xpath("//footer/button[@name='action_apply']")
        self.assertEqual(apply.get("type"), "object")
        self.assertTrue(apply.get("confirm"))
        self.assertTrue(arch.xpath("//footer/button[@special='cancel']"))
        [partners] = arch.xpath("//group[field[@name='partner_line_ids']]")
        self.assertEqual(partners.get("invisible"), "priority_key != 'partner'")
        arch = etree.fromstring(self.Batch.get_view(view_type="form")["arch"])
        [undo] = arch.xpath("//header/button[@string='Undo']")
        self.assertEqual(
            (undo.get("name"), undo.get("type"), undo.get("invisible")),
            ("action_undo_report", "object", "not crew_can_undo"),
        )
        self.assertTrue(undo.get("confirm"))

    # --- 32. Undo от отчета ---------------------------------------------------

    def test_32_1_crew_can_undo(self):
        """32.1: `crew_can_undo` — автор/мениджър, `applied`, не `train`, с
        поне един ред ≠ `unchanged`."""
        self._stale()
        batch = self._apply(self._wizard())
        self.assertTrue(batch.crew_can_undo)
        self.assertTrue(batch.with_user(self.manager).crew_can_undo)
        self.assertFalse(batch.with_user(self.mrp_user).crew_can_undo)
        batch.sudo().source = "train"
        self.assertFalse(batch.crew_can_undo)
        self.assertFalse(batch.with_user(self.manager).crew_can_undo)
        batch.sudo().source = "wizard"
        batch.line_ids.sudo().result = "unchanged"
        self.assertFalse(batch.crew_can_undo)
        batch.line_ids.sudo().result = "moved"
        self.assertTrue(batch.crew_can_undo)
        batch.action_undo()
        self.assertEqual(batch.state, "undone")
        self.assertFalse(batch.crew_can_undo)
        with self.assertRaises(UserError):
            batch.action_undo_report()
        # Партида `train` не се отменя (заварено), и от формата.
        self._stale()
        batch = self._apply(self._wizard())
        batch.sudo().source = "train"
        with self.assertRaises(UserError):
            batch.action_undo_report()
        self.assertEqual(batch.state, "applied")

    def test_32_2_undo_alternatives_exact(self):
        """32.2: съветник с `use_alternatives` (поръчката отива на
        алтернативния център) → Undo връща център, дати, писта и датите на
        МО от снимката точно; повторното Undo е безопасно."""
        self.wc_pg.alternative_workcenter_ids = self.wc_alt
        busy = self._make_wo(self.wc_pg, self._utc(MONDAY, 11), minutes=360)
        self._time_line(busy, self._utc(MONDAY, 7), self._utc(MONDAY, 7, 5))
        mo = self._mo()
        wo = self._stale(mo=mo)
        other = self._stale(workcenter=self.wc_alt)
        # Датите на МО — различни от новото място (иначе съвпадат с „сега“).
        mo.with_context(force_date=True).write(
            {"date_start": self._utc(FRIDAY, 9), "date_finished": self._utc(FRIDAY, 10)}
        )
        old = self._plan(wo)
        old_other = self._plan(other)
        old_mo = (mo.date_start, mo.date_finished)
        self.assertEqual(old_mo, (self._utc(FRIDAY, 9), self._utc(FRIDAY, 10)))
        batch = self._apply(
            self._wizard(
                workcenter_ids=[Command.set((self.wc_pg | self.wc_alt).ids)],
                use_alternatives=True,
            )
        )
        self.assertEqual(wo.workcenter_id, self.wc_alt)
        self.assertNotEqual((mo.date_start, mo.date_finished), old_mo)
        self.assertNotEqual(self._plan(other), old_other)
        self.assertTrue(batch.crew_can_undo)
        batch.action_undo_report()
        self.assertEqual(batch.state, "undone")
        self.assertEqual(self._plan(wo), old)
        self.assertEqual(self._plan(other), old_other)
        self.assertEqual((mo.date_start, mo.date_finished), old_mo)
        self.assertEqual(wo.leave_id.date_from, old[1])
        self.assertFalse(batch.crew_can_undo)
        # Повторното Undo не мести нищо.
        with self.assertRaises(UserError):
            batch.action_undo()
        self.assertEqual(self._plan(wo), old)
        self.assertEqual((mo.date_start, mo.date_finished), old_mo)

    def test_32_3_started_after_batch_partial(self):
        """32.3: поръчка, започната след партидата → `partial`, редът ѝ е
        `skipped`, другите се връщат."""
        first = self._stale()
        second = self._stale()
        old_second = self._plan(second)
        batch = self._apply(self._wizard())
        moved_first = self._plan(first)
        self._time_line(first, self._utc(MONDAY, 11), self._utc(MONDAY, 11, 5))
        batch.action_undo_report()
        self.assertEqual(batch.state, "partial")
        line = self._line(batch, first)
        self.assertEqual(line.result, "skipped")
        self.assertTrue(line.message)
        self.assertEqual(self._plan(first)[:3], moved_first[:3])
        self.assertEqual(self._plan(second), old_second)
        self.assertFalse(batch.crew_can_undo)

    def test_32_4_undo_recompute_keeps_split(self):
        """32.4 (Ф2-1): Undo на „Recompute“ връща плана; разделянето на
        приключените поръчки остава."""
        # МО-то остава отворено, иначе гардът M5.9 пропуска поръчката.
        done = self._make_wo(
            self.wc_pg,
            self._utc(MONDAY, 8),
            minutes=120,
            mo=self._keep_mo_open(self._mo()),
        )
        self._time_line(done, self._utc(MONDAY, 8), self._utc(MONDAY, 10))
        done.button_finish()
        self.assertEqual(done.state, "done")
        self.assertNotEqual(done.production_id.state, "done")
        stale = self._make_wo(self.wc_pg, self._utc(FRIDAY, 9), mo=self._mo())
        old = self._plan(stale)
        self._roster(self.wc_pg, MONDAY, "08:00", self.crew12)
        action = self.env["mrp.workcenter.roster"].with_context(
            crew_workcenter_id=self.wc_pg.id
        ).action_crew_recompute()
        batch = self.Batch.browse(action["res_id"])
        self.assertEqual(batch.source, "recompute")
        self.assertEqual(stale.date_start, self._utc(MONDAY, 11))
        self.assertEqual(set(done.time_ids.employee_id.ids), set(self.crew12.ids))
        self.assertTrue(batch.crew_can_undo)
        batch.action_undo_report()
        self.assertEqual(batch.state, "undone")
        self.assertEqual(self._plan(stale), old)
        self.assertEqual(
            set(done.time_ids.employee_id.ids), set(self.crew12.ids), "делено остава"
        )

    # --- 33. M9 отпада --------------------------------------------------------

    def test_33_m9_removed(self):
        """33: `source` няма `auto`; `_crew_run` няма `anchor`."""
        sources = dict(self.Batch._fields["source"].selection)
        self.assertNotIn("auto", sources)
        self.assertEqual(
            set(sources), {"wizard", "recompute", "drop", "train", "write"}
        )
        self.assertNotIn("anchor", inspect.signature(type(self.Batch)._crew_run).parameters)
        self.assertNotIn(
            "anchor", inspect.signature(type(self.Batch)._crew_candidates).parameters
        )
        # В 18 модулът се инсталира наново — миграцията auto → wizard (19.0.1.6.0)
        # няма място тук.

    # --- 36. Находките на проверката на фаза 2 (1.6.0) ------------------------

    def test_36_1_period_keeps_work_before_it(self):
        """36.1: Гантът е превъртян напред — периодът на съветника почва по-
        късно. Незапочнатите поръчки между днес и началото на периода не се
        пипат; тези в миналото (остарелите) отиват в периода."""
        next_monday = MONDAY + timedelta(days=7)
        tomorrow = self._make_wo(self.wc_pg, self._utc(TUESDAY, 9), mo=self._mo())
        stale = self._stale()
        old = self._plan(tomorrow)
        wizard = self.Wizard.with_context(
            crew_workcenter_ids=self.wc_pg.ids,
            crew_date_from=next_monday,
            crew_date_to=next_monday + timedelta(days=6),
        ).create({})
        self.assertEqual(wizard.date_from, next_monday)
        batch = self._apply(wizard)
        self.assertEqual(self._plan(tomorrow), old)
        self.assertNotIn(tomorrow, batch.line_ids.workorder_id)
        self.assertEqual(self._line(batch, stale).result, "moved")
        self.assertEqual(stale.date_start, self._utc(next_monday, 8))

    def test_36_2_undo_ignores_unchanged_moved_later(self):
        """36.2: ред `unchanged`, чиято поръчка е местена след партидата, не
        е конфликт — партидата не я е местила. Undo е пълно (`undone`), редът
        остава `unchanged`, поръчката си стои на новото място."""
        a = self._stale(mo=self._mo(deadline=self._utc(TUESDAY, 12)))
        self._apply(self._wizard())
        self.assertEqual(a.date_start, self._utc(MONDAY, 11))
        c = self._stale(mo=self._mo(deadline=self._utc(WEDNESDAY, 12)))
        old_c = self._plan(c)
        batch = self._apply(self._wizard())
        self.assertEqual(self._line(batch, a).result, "unchanged")
        self.assertEqual(self._line(batch, c).result, "moved")
        self.assertTrue(batch.crew_can_undo)
        a.write({"date_start": self._utc(TUESDAY, 14), "date_finished": self._utc(TUESDAY, 15)})
        batch.action_undo()
        self.assertEqual(batch.state, "undone")
        line = self._line(batch, a)
        self.assertEqual((line.result, line.message), ("unchanged", False))
        self.assertEqual(self._plan(c), old_c)
        self.assertEqual(
            (a.date_start, a.date_finished), (self._utc(TUESDAY, 14), self._utc(TUESDAY, 15))
        )

    def test_36_3_undo_mo_dates_follow_skipped(self):
        """36.3: МО на пропусната поръчка НЕ получава датите от снимката —
        те са = min/max на планираните ѝ поръчки (M6.8); МО на върнатата
        поръчка получава снимката точно."""
        mo_a = self._mo()
        mo_b = self._mo()
        a = self._stale(mo=mo_a)
        b = self._stale(mo=mo_b)
        for mo in mo_a | mo_b:
            mo.with_context(force_date=True).write(
                {"date_start": self._utc(FRIDAY, 9), "date_finished": self._utc(FRIDAY, 10)}
            )
        old_b = self._plan(b)
        batch = self._apply(self._wizard())
        self.assertEqual(self._line(batch, a).result, "moved")
        self.assertEqual(self._line(batch, b).result, "moved")
        # Поръчката на A е преместена след партидата (напр. със стрелката).
        a.write({"date_start": self._utc(TUESDAY, 9), "date_finished": self._utc(TUESDAY, 10)})
        batch.action_undo()
        self.assertEqual(batch.state, "partial")
        self.assertEqual(self._line(batch, a).result, "skipped")
        self.assertEqual(
            (a.date_start, a.date_finished), (self._utc(TUESDAY, 9), self._utc(TUESDAY, 10))
        )
        self.assertEqual((mo_a.date_start, mo_a.date_finished), (a.date_start, a.date_finished))
        self.assertEqual(self._plan(b), old_b)
        self.assertEqual(
            (mo_b.date_start, mo_b.date_finished), (self._utc(FRIDAY, 9), self._utc(FRIDAY, 10))
        )
