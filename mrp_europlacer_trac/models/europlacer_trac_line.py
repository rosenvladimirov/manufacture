# -*- coding: utf-8 -*-
"""Europlacer traceability lines — DATA MODEL ONLY (schema carrier).

Ported from the Odoo 11 ``europlacer`` connector (dXFactory) solely to transfer
the historical ``europlacer.trac.line`` records into Odoo 19 with full column
compatibility. NO business logic — only the field definitions.

O11→O19 adjustment: ``stock.production.lot`` → ``stock.lot`` (renamed in v15+).
"""
from odoo import fields, models


class EuroplacerTracLine(models.Model):
    _name = "europlacer.trac.line"
    _description = "Europlacer Traceability lines (data carrier)"
    # Таблицата е партиционирана по trac_id (RANGE) и е с 86M+ реда. Без
    # индекс всяка list-заявка е seq-scan+sort → timeout. Order по `id`
    # (raw колона, БЕЗ JOIN) + B-tree index на id (per-partition, Merge
    # Append) дава мигновена first-page. NB: order по `trac_id` (many2one)
    # би направил JOIN към europlacer.trac и order по името му — бавно;
    # затова order-ваме по id. Индексите (id, trac_id) се създават в
    # post_init hook (виж __init__/hooks) — иначе 86M са без индекс.
    _order = "id desc"

    trac_id = fields.Many2one(comodel_name="europlacer.trac", string="Trace header")
    production_id = fields.Integer(string="Production Order (raw id)",
                                   related="trac_id.production_id")
    dummy_batch = fields.Char(related="trac_id.dummy_batch", string="product batch number")

    position = fields.Integer("Position")
    # 🚨 Трансферираните O11 стойности в тези m2o сочат RAW O11 id-та, които
    # НЕ съществуват в mec-19 (product_id ~43% orphan, lot_id/pcb_* също).
    # Дори ЕДИН orphan в страницата чупи display_name → цялата list/form
    # заявка гърми („Record does not exist"). Затова ги пазим като RAW
    # Integer id-та (като package_id) — текстът е в dummy_* колоните. САМО
    # trac_id остава Many2one (доказано валиден, нужен за навигация към header).
    product_id = fields.Integer(string="Item (raw product id)")
    dummy_product_barcode = fields.Char("item code used for the production")
    dummy_product_name = fields.Char("item name")
    dummy_product_code = fields.Char("item code for reference")
    mark = fields.Char("Topographical mark")
    concerned_pattern = fields.Char("Concerned pattern")
    feeder_id = fields.Integer(string="Feeder (raw product id)")
    dummy_feeder_barcode = fields.Char("serial number of the feeder")
    dummy_batch_id = fields.Char("batch number of the item")
    location_id = fields.Integer(string="Slot (raw location id)")
    dummy_location_id = fields.Char("slot number of the feeder")
    lot_id = fields.Integer(string="Lot/Serial (raw stock.lot id)")
    dummy_lot_name = fields.Char("PCB Lot/Serial name")
    dummy_product_sn = fields.Char("pattern serial number")
    pcb_lot_id = fields.Integer(string="PCB Lot/Serial (raw stock.lot id)")
    pcb_product_id = fields.Integer(string="PCB Single (raw product id)")
    # stock.quant.package not present in this O19 build; keep raw reel id column
    package_id = fields.Integer("Reel (package raw id)")
    dummy_package_code = fields.Char("reel code")
    dummy_check_code = fields.Char("the electrical test procedure")
    tolerance = fields.Float("accepted tolerance in %")
    measure_theorical = fields.Float("theorical electrical value")
    measure = fields.Float("measured electrical value")

    # BRIN indexes — 87M rows; block-range indexes stay tiny.
    # trac_id is also the partition key (RANGE) → excellent correlation.
    _brin_trac_id = models.Index("USING brin (trac_id)")
    _brin_create_date = models.Index("USING brin (create_date)")
    _brin_lot_id = models.Index("USING brin (lot_id)")
    _brin_product_id = models.Index("USING brin (product_id)")
