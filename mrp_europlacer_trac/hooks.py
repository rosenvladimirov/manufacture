# -*- coding: utf-8 -*-
"""Post-init: индекси на партиционираната europlacer_trac_line (86M+ реда).

Таблицата се пълни чрез bulk трансфер БЕЗ индекси (за скорост на зареждане).
Без индекси всяка Odoo list-заявка е seq-scan + глобален sort през всички
партиции → timeout. Създаваме B-tree индекси на `id` (default _order) и
`trac_id` (партиционен ключ / филтри) — per-partition, дават Merge Append
ordered scan → мигновена first-page. `IF NOT EXISTS` = идемпотентно.
"""
import logging

_logger = logging.getLogger(__name__)

_INDEXES = [
    ("europlacer_trac_line_id_idx", "europlacer_trac_line", "id"),
    ("europlacer_trac_line_trac_id_idx", "europlacer_trac_line", "trac_id"),
    # групиране/филтри по lot (сериен номер) — иначе read_group = seq scan
    ("europlacer_trac_line_lot_id_idx", "europlacer_trac_line", "lot_id"),
    ("europlacer_trac_line_dummy_lot_name_idx", "europlacer_trac_line",
     "dummy_lot_name"),
]


def post_init_hook(env):
    cr = env.cr
    for name, table, col in _INDEXES:
        cr.execute(
            "SELECT 1 FROM pg_class WHERE relname=%s AND relkind IN ('r','p')",
            (table,))
        if not cr.fetchone():
            continue  # таблицата още не е конвертирана в партиционирана
        _logger.info("europlacer_trac: ensuring index %s on %s(%s)",
                     name, table, col)
        cr.execute(
            "CREATE INDEX IF NOT EXISTS %s ON %s (%s)"
            % (name, table, col))
    # partitionwise агрегация/join + повече parallel workers → read_group
    # (напр. group by lot сериен номер) пада от ~26s на ~8s на 86M реда.
    # Per-database (persistent, reload — не рестарт). Изисква права на
    # текущата база; best-effort.
    try:
        dbname = cr.dbname
        cr.execute(
            'ALTER DATABASE "%s" SET enable_partitionwise_aggregate=on' % dbname)
        cr.execute(
            'ALTER DATABASE "%s" SET enable_partitionwise_join=on' % dbname)
        cr.execute(
            'ALTER DATABASE "%s" SET max_parallel_workers_per_gather=8' % dbname)
        _logger.info("europlacer_trac: partitionwise aggregation enabled on %s",
                     dbname)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("europlacer_trac: could not set partitionwise params: %s",
                        exc)
