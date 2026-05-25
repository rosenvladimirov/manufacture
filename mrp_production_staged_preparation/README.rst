=================================
MRP Production Staged Preparation
=================================

Two-stage MO lifecycle gate: a manufacturing order can be confirmed in
**Intermediate** stage — production moves exist (forecast active), но Pick
Components / Store Finished pickings НЕ са родени. User triggers
**"Prepare for Production"** button when ready to materialise the transfers
— endpoints се swap-ват към буферните локации, native procurement ражда
pickings.

Принцип
=======

В междинния етап компонентният move сочи ``location_dest_id = Production`` и
``location_id = WH/Stock`` (bypass на буфера), готовият move сочи
``location_id = Production`` и ``location_dest_id = WH/Stock``. Pull rule-ите
не намират Stock↔buffer дупка → не раждат пикинги. Forecast вижда нуждата,
защото production moves съществуват в ``confirmed``.

При прехода към ``prepared``:

* 2-step warehouse (``pbm``) → raw moves' ``location_id`` се swap-ва на
  ``pbm_loc_id``. Pull rule ражда Pick (Stock → pbm_loc).
* 3-step warehouse (``pbm_sam``) → също finished moves' ``location_dest_id``
  се swap-ва на ``sam_loc_id``. Pull rule ражда и Store (sam_loc → Stock).
* 1-step warehouse (``mrp_one_step``) → no-op логистично; stage пак става
  ``prepared``.

Re-trigger е чрез ``stock.move._action_confirm(merge=False)``.

Procurement group
=================

При прехода към ``prepared`` модулът осигурява MO да има
``procurement_group_id`` (auto-create ако липсва) и сетва ``group_id`` на
засегнатите moves към тази group. Това предотвратява merge на новородените
Pick/Store pickings с pickings на други MO (merge ключът в ``stock.move``
включва ``group_id``).

Конфигурация
============

Активирай **Staged Preparation** на ``stock.picking.type`` (manu type)
където искаш този flow:

  Inventory → Configuration → Operations Types → <твоят manu type> →
  General → Staged Preparation → ✓

MO-та с picking types БЕЗ флага продължават да работят 100% нативно.

Ограничения (Phase 1)
=====================

* Reverse transition ``prepared → intermediate`` НЕ е поддържан. Изисква cancel
  на родените Pick/Store + restore на endpoints — висок риск.
* Multi-level BoM: модулът действа само на текущото MO, не каскадно.

Стандартни Odoo полета използвани
=================================

* ``stock.warehouse.lot_stock_id`` — WH/Stock главна локация
* ``stock.warehouse.pbm_loc_id`` — Pre-production buffer (2/3-step)
* ``stock.warehouse.sam_loc_id`` — Post-production buffer (3-step)
* ``stock.warehouse.manufacture_steps`` — selection (mrp_one_step/pbm/pbm_sam)
* ``mrp.production.production_location_id`` — Production локация (фиксирана ос)
* ``mrp.production.location_src_id`` / ``location_dest_id`` — MO endpoints

Никой от тези не се пренаписва — модулът само replicates ги в move values.
