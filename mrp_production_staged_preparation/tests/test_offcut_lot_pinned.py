# -*- coding: utf-8 -*-
"""Остатъкът каца със СВОЯ лот, не с този на целия прът.

🔴 ДЕФЕКТЪТ (мерено на fulltest 03.09, WH/MO/00298):

    stock.move 8743   is_staged_offcut=True · forced_lot_ids=[312]   иска новия
    stock.move.line   lot_id = 5 („6500")                            каца със стария
    quant за OFF- лотовете 308–312                                   НУЛА записа
    quant в Remnant/Offcut            8.39 м „6500" · 5.35 м „6500"

Партида „6500" твърди „това са пръти 6500 мм". Осем метра остатък с такава
партида се броят за наличност и влизат във „Free Stock in Transit", а за рязане
не стават. Мерено: 6 от 7 количества в склада не са кратни на дължината на пръта.

🔑 ПРИЧИНАТА: `forced_lot_ids` се прилага в `_action_assign`, и то само върху
редове с ПРАЗЕН `lot_id`. Това движение тръгва от виртуална локация с готово
`quantity` и `picked=True` — `_action_assign` не се вика изобщо.
"""
from odoo.tests.common import TransactionCase


class TestOffcutLotPinned(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # ⚠️ НЕ създаваме продукт: базата носи задължителни полета от други
        # модули и всяко ново ще чупи теста. Взимаме прът, какъвто вече има —
        # това е и по-близо до живия случай.
        cls.produkt = cls.env["product.product"].search(
            [("tracking", "=", "lot"), ("is_storable", "=", True)], limit=1)
        if not cls.produkt:
            cls.skipTest(cls, "no lot-tracked storable product on this database")

        cls.cyal = cls.env["stock.lot"].create({
            "name": "6500-pin-test", "product_id": cls.produkt.id})
        cls.ostatak = cls.env["stock.lot"].create({
            "name": "OFF-2350-P1-1-pin-test", "product_id": cls.produkt.id})
        wh = cls.env["stock.warehouse"].search([], limit=1)
        # ⚠️ По ПРЕДНАЗНАЧЕНИЕ, не по XML id: `stock.location_production` не
        # съществува във всяка база, а точно виртуалната производствена локация
        # прави случая — от нея тръгва by-product движението и затова
        # `_action_assign` не се вика.
        cls.prod_loc = cls.env["stock.location"].search(
            [("usage", "=", "production")], limit=1)
        cls.dest = wh.lot_stock_id
        # ⚠️ Тестът иска `forced_lot_ids`, а модулът НЕ зависи от модула, който
        # го дава. При ъпгрейд само на този модул полето липсва в регистъра —
        # тогава няма какво да се проверява и тестът се пропуска, вместо да
        # гърми за нещо, което по построение може да го няма.
        if "forced_lot_ids" not in cls.env["stock.move"]._fields:
            cls.skip_all = True

    def setUp(self):
        super().setUp()
        if getattr(self, "skip_all", False):
            self.skipTest("stock_move_forced_lot_multi is not in this registry")

    def _move(self, with_line_lot=None):
        move = self.env["stock.move"].create({
            "name": "offcut pin test",
            "product_id": self.produkt.id,
            "product_uom": self.produkt.uom_id.id,
            "product_uom_qty": 2.35,
            "quantity": 2.35,
            "location_id": self.prod_loc.id,
            "location_dest_id": self.dest.id,
            "is_staged_offcut": True,
            "forced_lot_ids": [(6, 0, self.ostatak.ids)],
            "state": "draft",
        })
        if with_line_lot is not None:
            self.env["stock.move.line"].create({
                "move_id": move.id,
                "product_id": self.produkt.id,
                "product_uom_id": self.produkt.uom_id.id,
                "location_id": self.prod_loc.id,
                "location_dest_id": self.dest.id,
                "lot_id": with_line_lot.id,
                "quantity": 2.35,
            })
        return move

    def test_wrong_lot_on_the_line_is_replaced(self):
        """Линия със стария лот се пренаписва с остатъчния.

        Това е живият случай: Odoo е сложил партидата на целия прът.
        """
        move = self._move(with_line_lot=self.cyal)
        move._staged_pin_offcut_lot()
        self.assertEqual(
            move.move_line_ids.lot_id, self.ostatak,
            "Остатъкът остана с партидата на целия прът — тя твърди, че това са "
            "пръти 6500 мм, и складът ги брои за налични.")

    def test_line_is_created_when_missing(self):
        """Няма ли линия, прави се — инак Odoo ще избере лот сам при done."""
        move = self._move()
        move._staged_pin_offcut_lot()
        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids.lot_id, self.ostatak)

    def test_other_moves_are_not_touched(self):
        """Пипа се САМО `is_staged_offcut`.

        ⛔ Обикновено движение с forced_lot_ids минава през `_action_assign`,
        където правилото „само празен lot_id" е нарочно — то пази резервацията
        на Odoo. Тук не бива да се намесваме.
        """
        move = self._move(with_line_lot=self.cyal)
        move.is_staged_offcut = False
        move._staged_pin_offcut_lot()
        self.assertEqual(
            move.move_line_ids.lot_id, self.cyal,
            "Пипнато е движение, което не е остатъчно.")
