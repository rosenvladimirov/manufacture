# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
#
# Покритието пази трите предпазни мерки от спецификацията. Всяка от тях е тук,
# защото нарушаването ѝ е ТИХО — нищо не гърми, просто снабдяването започва да
# поръчва грешни количества.
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderpointBarMultiple(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1)
        cls.uom_m = cls.env.ref("uom.product_uom_meter")
        cls.product = cls.env["product.product"].create({
            "name": "Test Bar 6m",
            "is_storable": True,
            "tracking": "lot",
            "uom_id": cls.uom_m.id,
            "uom_po_id": cls.uom_m.id,
        })

    def _lot(self, product=None, bar_mm=6000.0, offcut=False, offcut_mm=0.0):
        return self.env["stock.lot"].create({
            "name": "L-%s-%s" % (bar_mm, "off" if offcut else "full"),
            "product_id": (product or self.product).id,
            "bar_length_mm": bar_mm,
            "is_offcut": offcut,
            "offcut_length_mm": offcut_mm,
        })

    def _orderpoint(self, product=None, **vals):
        return self.env["stock.warehouse.orderpoint"].create(dict({
            "warehouse_id": self.warehouse.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "product_id": (product or self.product).id,
            "product_min_qty": 0.0,
            "product_max_qty": 0.0,
        }, **vals))

    # ── Мярка 1: посява се при създаване ──────────────────────────────────
    def test_seeds_from_full_bar_on_create(self):
        """6000 mm лот → кратно 6.0 в метри (UoM на продукта)."""
        self._lot(bar_mm=6000.0)
        op = self._orderpoint()
        self.assertEqual(op.qty_multiple, 6.0)
        self.assertFalse(op.manual_qty_multiple_set,
                         "посятото НЕ е ръчно решение и не бива да се заключва")

    def test_seed_converts_mm_to_uom(self):
        """6500 mm → 6.5, а не 6500. Полето е в UoM на продукта."""
        self._lot(bar_mm=6500.0)
        self.assertEqual(self._orderpoint().qty_multiple, 6.5)

    def test_no_lot_leaves_multiple_untouched(self):
        """Без лот няма какво да посеем — не измисляме стойност.

        ⚠️ Очакваме 1.0, не 0.0: ядрото дава на `qty_multiple` подразбиращо се
        **1.0**. Точно това ни хвана при първия пуск и е причината гардът в
        посяването да гледа ФЛАГА, а не стойността — иначе модулът е тих no-op.
        """
        other = self.env["product.product"].create({
            "name": "No Lot Product", "is_storable": True, "uom_id": self.uom_m.id})
        self.assertEqual(self._orderpoint(product=other).qty_multiple, 1.0)

    # ── Мярка 2: НИКОГА от остатъци ───────────────────────────────────────
    def test_offcut_lot_is_never_used(self):
        """Остатъкът не е поръчваемо количество — не бива да ражда кратно.

        Регресионен: остатъчни лотове се раждат при ВСЯКА оптимизация, тоест без
        този гард всеки разкрой би добавил ново „кратно" като 2.3 м.
        Остава ядреният default 1.0, тоест НЕ е посявано от остатъка.
        """
        self._lot(bar_mm=2300.0, offcut=True, offcut_mm=2300.0)
        self.assertEqual(self._orderpoint().qty_multiple, 1.0)

    def test_full_bar_wins_over_offcut(self):
        """При смесени лотове се взима пълният прът, не остатъкът."""
        self._lot(bar_mm=6000.0)
        self._lot(bar_mm=2300.0, offcut=True, offcut_mm=2300.0)
        self.assertEqual(self._orderpoint().qty_multiple, 6.0)

    # ── Мярка 3: ръчното побеждава и се заключва ──────────────────────────
    def test_manual_entry_locks(self):
        """Въведеният сноп вдига флага и спира автоматиката."""
        self._lot(bar_mm=6000.0)
        op = self._orderpoint()
        op.qty_multiple = 72.0          # сноп от 12 пръта по 6 м
        self.assertTrue(op.manual_qty_multiple_set)
        op._seed_qty_multiple_from_bar_length()
        self.assertEqual(op.qty_multiple, 72.0,
                         "посяването НЕ бива да връща пръта върху въведения сноп")

    def test_explicit_value_on_create_is_not_overwritten(self):
        """Кратно, зададено при създаването, оцелява посяването."""
        self._lot(bar_mm=6000.0)
        self.assertEqual(self._orderpoint(qty_multiple=72.0).qty_multiple, 72.0)

    def test_explicit_zero_on_create_does_not_lock(self):
        """🔴 РЕГРЕСИОНЕН: нулата в vals НЕ е решение и НЕ бива да заключва.

        Открито върху реални данни, не в теста: PML създава orderpoint-ите с
        изричен `qty_multiple: 0`. Докато нулата вдигаше флага, 80 orderpoint-а
        излязоха заключени с кратно 0 — тоест посяването се прескачаше завинаги
        точно там, където има смисъл, и модулът беше безполезен, без да гръмне.
        """
        self._lot(bar_mm=6000.0)
        op = self._orderpoint(qty_multiple=0.0)
        self.assertFalse(op.manual_qty_multiple_set,
                         "нулата не е човешко решение — не заключва")
        self.assertEqual(op.qty_multiple, 6.0, "посяването трябва да е минало")

    def test_write_zero_does_not_lock(self):
        """Автоматика, която изчиства кратното, не бива да затваря посяването."""
        self._lot(bar_mm=6000.0)
        op = self._orderpoint()
        op.qty_multiple = 0.0
        self.assertFalse(op.manual_qty_multiple_set)

    def test_reset_button_unlocks_and_reseeds(self):
        """Връщането към пръта е ИЗРИЧНО действие, не страничен ефект."""
        self._lot(bar_mm=6000.0)
        op = self._orderpoint()
        op.qty_multiple = 72.0
        op.action_reset_qty_multiple_to_bar()
        self.assertFalse(op.manual_qty_multiple_set)
        self.assertEqual(op.qty_multiple, 6.0)

    def test_seeding_does_not_raise_manual_flag(self):
        """Вътрешното писане се различава от външното по контекстния ключ."""
        self._lot(bar_mm=6000.0)
        op = self._orderpoint()
        self.assertEqual(op.qty_multiple, 6.0)
        self.assertFalse(op.manual_qty_multiple_set)
