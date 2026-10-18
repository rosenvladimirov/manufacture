# Copyright 2025-2026 Rosen Vladimirov
#
# This file is available under a DUAL LICENSE:
#   1. GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
#      https://www.gnu.org/licenses/agpl-3.0.html
#   2. A commercial license from Rosen Vladimirov, for use without the obligations
#      of the AGPL. See LICENSE-COMMERCIAL.md. Contact: vladimirov.rosen@gmail.com
#
# Unless you hold a valid commercial license, your use of this file is governed
# by the AGPL-3.0-or-later.

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestForcedLotMulti(TransactionCase):
    """Тестове за 19-ия порт на 18.0.4.3.1 (git репото; №118 от прода — в test_bar_po_without_lot).

    Покриват: разцепването на набавяне по лот (force_split / po_split),
    ключа за сливане на набавяния, _find_candidate при po_split,
    попълването на lot_id в move line-ите, лот под-правилата на
    точките за презареждане и default лота от реда на BoM.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.partner = cls.env["res.partner"].create({"name": "Forced Lot Vendor"})
        cls.product = cls.env["product.product"].create({
            "name": "Forced Lot Component",
            "is_storable": True,
            "tracking": "lot",
        })
        cls.lot_a = cls.env["stock.lot"].create({
            "name": "FLM-A", "product_id": cls.product.id,
        })
        cls.lot_b = cls.env["stock.lot"].create({
            "name": "FLM-B", "product_id": cls.product.id,
        })
        cls.lot_c = cls.env["stock.lot"].create({
            "name": "FLM-C", "product_id": cls.product.id,
        })

    def _procurement(self, qty, lots, **extra_values):
        values = {
            "forced_lot_ids": lots,
            "propagate_cancel": False,
            "company_id": self.company,
            "warehouse_id": self.warehouse,
        }
        values.update(extra_values)
        return self.env["stock.rule"].Procurement(
            self.product, qty, self.product.uom_id, self.stock_location,
            "FLM", "FLM-TEST", self.company, values,
        )

    # ------------------------------------------------------------ split

    def test_split_force_split_reduces_parent(self):
        """force_split лот се отделя с split_buffer_qty; родителят намалява."""
        self.lot_a.write({"force_split": True, "split_buffer_qty": 3.0})
        procs = self.env["stock.rule"]._split_forced_lot_procurements(
            [self._procurement(10.0, self.lot_a | self.lot_b)]
        )
        self.assertEqual(len(procs), 2)
        by_lots = {frozenset(p.values["forced_lot_ids"].ids): p for p in procs}
        self.assertAlmostEqual(by_lots[frozenset(self.lot_a.ids)].product_qty, 3.0)
        self.assertAlmostEqual(by_lots[frozenset(self.lot_b.ids)].product_qty, 7.0)

    def test_split_po_split_even_drops_parent(self):
        """po_split лотове делят количеството поравно; родителят отпада."""
        (self.lot_a | self.lot_b).write({"po_split": True})
        procs = self.env["stock.rule"]._split_forced_lot_procurements(
            [self._procurement(10.0, self.lot_a | self.lot_b)]
        )
        self.assertEqual(len(procs), 2)
        for proc in procs:
            self.assertEqual(len(proc.values["forced_lot_ids"]), 1)
            self.assertAlmostEqual(proc.product_qty, 5.0)

    def test_split_without_flags_is_noop(self):
        """Без флагове набавянето минава непроменено."""
        proc = self._procurement(10.0, self.lot_a | self.lot_b)
        procs = self.env["stock.rule"]._split_forced_lot_procurements([proc])
        self.assertEqual(procs, [proc])

    def test_merge_groupby_key_differs_by_lots(self):
        """Набавяния с различни forced лотове не се сливат в един PO ред."""
        Rule = self.env["stock.rule"]
        key_a = Rule._get_procurements_to_merge_groupby(
            self._procurement(1.0, self.lot_a))
        key_b = Rule._get_procurements_to_merge_groupby(
            self._procurement(1.0, self.lot_b))
        key_a2 = Rule._get_procurements_to_merge_groupby(
            self._procurement(2.0, self.lot_a))
        self.assertNotEqual(key_a, key_b)
        self.assertEqual(key_a, key_a2)

    # ------------------------------------------------------------ purchase

    def test_find_candidate_po_split_requires_same_lots(self):
        """При po_split се приема само ред със същия набор лотове."""
        (self.lot_a | self.lot_b).write({"po_split": True})
        po = self.env["purchase.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "product_qty": 1.0,
                "forced_lot_ids": [Command.set(self.lot_a.ids)],
            })],
        })
        line = po.order_line
        base_values = {
            "propagate_cancel": line.propagate_cancel,
            "orderpoint_id": self.env["stock.warehouse.orderpoint"],
            "move_dest_ids": self.env["stock.move"],
        }
        args = (self.product, 1.0, self.product.uom_id, self.stock_location,
                "FLM", "FLM-TEST", self.company)
        self.assertEqual(
            line._find_candidate(*args, dict(base_values, forced_lot_ids=self.lot_a)),
            line,
        )
        self.assertFalse(
            line._find_candidate(*args, dict(base_values, forced_lot_ids=self.lot_b))
        )

    def test_po_line_lots_flow_to_receipt(self):
        """Лотовете от PO реда стигат до входящото движение и до lot_id."""
        po = self.env["purchase.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "product_qty": 4.0,
                "forced_lot_ids": [Command.set((self.lot_a | self.lot_b).ids)],
            })],
        })
        po.button_confirm()
        move = po.picking_ids.move_ids
        self.assertEqual(move.forced_lot_ids, self.lot_a | self.lot_b)
        self.assertEqual(move.move_line_ids.lot_id, self.lot_a | self.lot_b)
        self.assertAlmostEqual(sum(move.move_line_ids.mapped("quantity")), 4.0)

    # ------------------------------------------------------------ move lines

    def _incoming_move(self, qty, lots):
        move = self.env["stock.move"].create({
            "product_id": self.product.id,
            "product_uom_qty": qty,
            "product_uom": self.product.uom_id.id,
            "location_id": self.supplier_location.id,
            "location_dest_id": self.stock_location.id,
            "picking_type_id": self.warehouse.in_type_id.id,
            "forced_lot_ids": [Command.set(lots.ids)],
        })
        move._action_confirm()
        return move

    def test_fill_single_lot(self):
        """Един forced лот попълва всички празни линии."""
        move = self._incoming_move(6.0, self.lot_a)
        move._action_assign()
        self.assertTrue(move.move_line_ids)
        self.assertEqual(move.move_line_ids.lot_id, self.lot_a)

    def test_fill_multi_lot_splits_single_line(self):
        """Няколко лота разцепват единствената празна линия pro-rata."""
        move = self._incoming_move(9.0, self.lot_a | self.lot_b | self.lot_c)
        move._action_assign()
        self.assertEqual(len(move.move_line_ids), 3)
        self.assertEqual(move.move_line_ids.lot_id, self.lot_a | self.lot_b | self.lot_c)
        for ml in move.move_line_ids:
            self.assertAlmostEqual(ml.quantity, 3.0)

    def test_fill_keeps_manual_lot_name(self):
        """Ръчно въведено lot_name не се презаписва."""
        move = self._incoming_move(2.0, self.lot_a)
        move._action_assign()
        move.move_line_ids.write({"lot_id": False, "lot_name": "MANUAL-1"})
        move._forced_lot_fill_empty_lines()
        self.assertFalse(move.move_line_ids.lot_id)
        self.assertEqual(move.move_line_ids.lot_name, "MANUAL-1")

    def test_moves_with_different_lots_do_not_merge(self):
        self.assertIn(
            "forced_lot_ids",
            self.env["stock.move"]._prepare_merge_moves_distinct_fields(),
        )

    def test_wizard_adds_lots(self):
        move = self._incoming_move(1.0, self.lot_a)
        action = move.action_open_forced_lot_wizard()
        self.assertEqual(action["context"]["default_move_id"], move.id)
        wizard = self.env[action["res_model"]].create({
            "move_id": move.id,
            "lot_ids": [Command.set(self.lot_b.ids)],
        })
        wizard.action_apply()
        self.assertEqual(move.forced_lot_ids, self.lot_a | self.lot_b)

    # ------------------------------------------------------------ orderpoints

    def _parent_orderpoint(self):
        return self.env["stock.warehouse.orderpoint"].create({
            "product_id": self.product.id,
            "warehouse_id": self.warehouse.id,
            "location_id": self.stock_location.id,
            "product_min_qty": 0.0,
            "product_max_qty": 0.0,
        })

    def test_orderpoint_child_inherits_and_locks_lot(self):
        """Под-правило на същия продукт/локация е позволено (ядреното
        уникално ограничение е подменено) и заключва набавянето за лота."""
        parent = self._parent_orderpoint()
        child = self.env["stock.warehouse.orderpoint"].create({
            "parent_id": parent.id,
            "lot_id": self.lot_a.id,
            "product_min_qty": 1.0,
            "product_max_qty": 5.0,
        })
        self.assertEqual(child.product_id, self.product)
        self.assertEqual(child.location_id, self.stock_location)
        self.assertTrue(child.is_lot_child)
        self.assertFalse(parent.is_lot_child)
        self.assertEqual(parent.child_count, 1)
        self.assertEqual(parent._get_qty_to_order(), 0.0)
        self.assertEqual(child._get_product_context().get("lot_id"), self.lot_a.id)
        self.assertEqual(child._prepare_procurement_values()["forced_lot_ids"], self.lot_a)

    def test_orderpoint_child_requires_lot(self):
        """Под-правило без лот се отказва: или от частичния индекс на
        родителите (lot_id IS NULL), или от Python ограничението."""
        parent = self._parent_orderpoint()
        # Odoo 19 BaseCase._assertRaises вика issubclass(exception, AccessError)
        # (odoo/tests/common.py:507) — кортеж от изключения там гърми с
        # TypeError, затова изключението е едно. INSERT-ът пада на частичния
        # индекс на родителите преди Python ограниченията.
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.env["stock.warehouse.orderpoint"].create({"parent_id": parent.id})
            self.env.flush_all()

    def test_orderpoint_child_lot_unique_per_parent(self):
        parent = self._parent_orderpoint()
        self.env["stock.warehouse.orderpoint"].create({
            "parent_id": parent.id, "lot_id": self.lot_a.id,
        })
        # Дубликатът пада на индекса _parent_lot_idx при INSERT-а.
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.env["stock.warehouse.orderpoint"].create({
                "parent_id": parent.id, "lot_id": self.lot_a.id,
            })
            self.env.flush_all()

    def test_orderpoint_parent_still_unique(self):
        """Частичният индекс пази уникалността на родителите."""
        self._parent_orderpoint()
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._parent_orderpoint()
            self.env.flush_all()

    def test_orderpoint_max_depth(self):
        parent = self._parent_orderpoint()
        child = self.env["stock.warehouse.orderpoint"].create({
            "parent_id": parent.id, "lot_id": self.lot_a.id,
        })
        with self.assertRaises(ValidationError):
            self.env["stock.warehouse.orderpoint"].create({
                "parent_id": child.id, "lot_id": self.lot_b.id,
            })

    # ------------------------------------------------------------ BoM default lot

    def test_bom_line_default_forced_lot(self):
        finished = self.env["product.product"].create({
            "name": "Forced Lot Finished", "is_storable": True,
        })
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": finished.product_tmpl_id.id,
            "product_qty": 1.0,
            "bom_line_ids": [Command.create({
                "product_id": self.product.id,
                "product_qty": 2.0,
                "default_forced_lot_id": self.lot_a.id,
            })],
        })
        production = self.env["mrp.production"].create({
            "product_id": finished.id,
            "bom_id": bom.id,
            "product_qty": 1.0,
        })
        raw = production.move_raw_ids.filtered(lambda m: m.product_id == self.product)
        self.assertEqual(raw.forced_lot_ids, self.lot_a)
        self.assertEqual(production.forced_lot_ids, self.lot_a)
