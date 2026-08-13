# -*- coding: utf-8 -*-
"""Europlacer traceability header — DATA MODEL ONLY (schema carrier).

Ported from the Odoo 11 ``europlacer`` connector (dXFactory) solely to transfer
the historical ``europlacer.trac`` records into Odoo 19 with full column
compatibility. NO business logic (no XML/CSV parsing, watchdog, queue_job
populate, cron, onchange/compute pipelines) — only the field definitions.

O11→O19 adjustments (schema only):
- ``stock.production.lot`` → ``stock.lot`` (model renamed in v15+).
- Many2one to europlacer sibling tables NOT in scope (europlacer.trac.rc / .tr
  / .stage) kept as plain Integer so the raw id column still transfers.
- Dropped mail.thread/mail.activity.mixin, One2many to europlacer.warehouse
  (out of scope) and all defaults/group_expand/tracking (behaviour, not data).
"""
from odoo import fields, models


class EuroplacerTrac(models.Model):
    _name = "europlacer.trac"
    _description = "Europlacer Traceability (data carrier)"
    _order = "begin_date_trac desc"

    name = fields.Char(string='Reference/Description', index=True, copy=False)
    # --- CFX-IPC ingestion keys (populated in CFX/AMQP mode) ---
    transaction_id = fields.Char("CFX TransactionId", index=True, copy=False,
                                 help="CFX work GUID; idempotency key for AMQP ingestion")
    cfx_handle = fields.Char("CFX Handle", help="Source machine CFX handle")
    source_mode = fields.Selection([('csv', 'CSV upload'), ('cfx', 'CFX-IPC AMQP')],
                                    string="Ingestion mode", default='csv', index=True)
    result = fields.Char("Work result", help="WorkCompleted result: Completed / Aborted")
    station_state = fields.Char("Last station state")
    filename = fields.Char("File name")
    begin_date_trac = fields.Datetime("Start production")
    dummy_begin_date = fields.Char("Start production")
    end_date_trac = fields.Datetime("End production")
    dummy_end_date = fields.Char("End production")
    product_id = fields.Integer("Product (raw id)")
    dummy_product_id = fields.Char("product reference")
    dummy_barcode = fields.Char("product serial number")
    batch = fields.Char('Batch')
    production_id = fields.Integer("Production Order (raw id)")
    dummy_production_id = fields.Char("Production Order")
    workorder_id = fields.Integer("Work Order (raw id)")
    dummy_workorder_id = fields.Char("Work Order")
    final_lot_id = fields.Integer("Lot/Serial Number (raw id)")
    dummy_batch = fields.Char("product batch number", index=True)
    # europlacer.trac.rc — out of scope; keep raw id column for transfer
    software_rc_version = fields.Integer("RC software version (raw id)")
    dummy_rc_version = fields.Char("version of RC software")
    # europlacer.trac.tr — out of scope; keep raw id column for transfer
    software_tr_version = fields.Integer("TR file version (raw id)")
    dummy_tr_version = fields.Char("version of the traceability file")
    date_lib = fields.Date("Date item lib")
    date_plib = fields.Date("Date package lib")
    warehouse_id = fields.Integer("Warehouse (raw id)")
    location_id = fields.Integer("Default Source Location (raw id)")
    workcenter_id = fields.Integer("Work Center (raw id)")
    dummy_workcenter_id = fields.Char("Europlacer machine identification")
    partner_id = fields.Integer("Partner (raw id)")
    error_index = fields.Char("Program issue")
    dummy = fields.Integer("Save current row")
    note = fields.Html('File informations')
    location_dest_id = fields.Integer("Destination Location (raw id)")
    lines = fields.One2many(comodel_name="europlacer.trac.line",
                            inverse_name="trac_id", string="Trace details")
    # europlacer.trac.stage — out of scope; keep raw id column for transfer
    stage_id = fields.Integer("Stage (raw id)")

    # BRIN indexes — block-range, cheap on the large history table
    _brin_begin_date_trac = models.Index("USING brin (begin_date_trac)")
    _brin_create_date = models.Index("USING brin (create_date)")
