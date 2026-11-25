# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1
"""Shop Floor „Човеци“ / „Смяна/Бригада“ през браузъра (Росен 15.10.2026)."""
from datetime import date, timedelta

from odoo.tests import HttpCase, tagged

from odoo.addons.planning_crew_rotation.tests.test_crew_rotation import _with_contract


@tagged("post_install", "-at_install")
class TestShopFloorShiftTour(HttpCase):

    def test_crew_shift_in_the_shop_floor(self):
        env = self.env(context=dict(self.env.context, lang="en_US"))
        admin = env.ref("base.user_admin")
        # тестът търси английските надписи; панелът с хора иска групата за работни поръчки
        admin.write({"lang": "en_US", "groups_id": [(4, env.ref("mrp.group_mrp_routings").id)]})
        # в пълна база служителят на админа може да е архивиран — тогава се връща
        own = env["hr.employee"].with_context(active_test=False).search(
            [("user_id", "=", admin.id), ("company_id", "=", env.company.id)], limit=1)
        if own:
            own.active = True
        else:
            env["hr.employee"].create({"name": "Admin employee", "user_id": admin.id})
        Template = env["planning.slot.template"]
        day = Template.create({"start_time": 7.0, "end_time": 19.0, "duration_days": 1})
        night = Template.create({"start_time": 19.0, "end_time": 7.0, "duration_days": 2})
        rotation = env["planning.crew.rotation"].create({
            "name": "Extrusion (shift tour)", "day_template_id": day.id,
            "night_template_id": night.id, "anchor_date": date.today().replace(day=1),
            "preset": "2-2-4"})
        rotation.action_load_preset()
        rotation.action_approve()
        crew = rotation.crew_ids.sorted("offset_days")[0]
        leader, worker = _with_contract(env, [
            {"name": "Tour leader A"}, {"name": "Tour worker A2"}])
        for employee in leader | worker:
            env["planning.crew.membership"].create({
                "contract_id": employee.contract_id.id, "crew_id": crew.id,
                "date_from": date.today() - timedelta(days=1)})
        crew.leader_id = leader
        leader.pin = "1234"
        workcenter = env["mrp.workcenter"].create({"name": "Extruder (shift tour)"})
        product = env["product.product"].create({"name": "Film (shift tour)", "is_storable": True})
        granule = env["product.product"].create({"name": "Granule (shift tour)"})
        bom = env["mrp.bom"].create({
            "product_tmpl_id": product.product_tmpl_id.id, "product_id": product.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": granule.id, "product_qty": 1.0})],
            "operation_ids": [(0, 0, {"name": "extrusion", "workcenter_id": workcenter.id})],
        })
        mo = env["mrp.production"].create({"product_id": product.id, "bom_id": bom.id, "product_qty": 1.0})
        mo.action_confirm()
        self.start_tour("/odoo/shop-floor", "crew_shift_shop_floor", login="admin")
