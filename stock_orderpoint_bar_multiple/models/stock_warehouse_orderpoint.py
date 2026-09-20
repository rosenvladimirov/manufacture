# Copyright 2026 Rosen Vladimirov, Terraros Commerce Ltd.
# License OPL-1 (Odoo Proprietary License v1.0)
#
# ЗАЩО СЪЩЕСТВУВА ТОЗИ МОДУЛ
#
# Прътовите материали се купуват на цели прътове или на снопове, но `qty_multiple`
# по подразбиране е 0, а ядрото документира нулата дословно като „If it is 0, it is
# not rounded" — тоест снабдяването може да поръча 13.7 м вместо цели прътове, и
# това става ТИХО. Доставчиковото `min_qty` не помага: то е минимално количество за
# дадена цена, не кратно.
#
# Реалните снопове (4-82 пръта при PVC, 10 или 12 при армировките, а алуминият
# изобщо няма снопове) НЕ идват от LogiKal — проверено: експортът описва парчето
# (Amount, Units, Length, Width, Depth, Weight), не как се купува. Затова снопът се
# въвежда ръчно и ПОСТЕПЕННО, което значи, че винаги ще има материал без опаковка.
#
# Решението (спецификация на Любомир Топалов, 28.07.2026): за периода без опаковка
# кратното се посява от дължината на ЦЕЛИЯ ПРЪТ. Не е точно, но е ВИНАГИ валидно —
# цял прът е поръчваемо количество. Тихият случай изчезва.
import logging

from odoo import api, fields, models
from odoo.tools import float_round

_logger = logging.getLogger(__name__)

# Контекстен ключ: вдига се само докато посяваме, за да не се сметне посятата
# стойност за ръчен избор на потребителя.
SEED_CTX = "orderpoint_bar_multiple_seeding"


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    manual_qty_multiple_set = fields.Boolean(
        string="Manual Order Multiple",
        default=False,
        copy=False,
        help="Internal flag — True once the multiple was set by a user or by a "
             "purchase packaging. Keeps the seeding from overwriting that value.",
    )

    # ------------------------------------------------------------------
    # Посяване
    # ------------------------------------------------------------------
    # ⚠️ НАРОЧНО НЕ Е `compute`. Изкушението е голямо, защото съседният модул
    # (`partner_default_lead_time`) решава същия проблем със `lead_time_days` +
    # `manual_lead_time_set` през compute — и флаг-механизмът е копиран оттам.
    # Но при него ИЗТОЧНИКЪТ Е ЖИВ: доставчиковата отсрочка се мени и стойността
    # трябва да я следи. Тук е обратното — спецификацията иска „посява се веднъж
    # при създаването и НИКОГА не се пресява". Compute по дефиниция се
    # преизчислява, тоест първото задействане на depends би върнало дължината на
    # пръта върху вече въведения сноп. Затова посяването живее в `create()`.

    @api.model_create_multi
    def create(self, vals_list):
        # Изричното кратно при създаване е РЕШЕНИЕ и се заключва веднага — иначе
        # посяването по-долу би го изяло.
        #
        # 🔴 НО САМО НЕНУЛЕВОТО. Открито върху реални данни: PML създава
        # orderpoint-ите с изричен `qty_multiple: 0` в vals. Заключването на
        # нулата обезсмисляше целия модул — 80 orderpoint-а излязоха с вдигнат
        # флаг и кратно 0, тоест посяването се прескачаше ЗАВИНАГИ точно за
        # материалите, за които съществува. А нулата НЕ е решение на човек: тя е
        # ядреното „не закръгляй" и е именно тихият случай, който гоним.
        for vals in vals_list:
            if vals.get("qty_multiple"):
                vals.setdefault("manual_qty_multiple_set", True)
        orderpoints = super().create(vals_list)
        orderpoints._seed_qty_multiple_from_bar_length()
        return orderpoints

    def _seed_qty_multiple_from_bar_length(self):
        """Посява кратното от стандартната дължина на пръта — веднъж, при създаване.

        ⚠️ АВТОРИТЕТЪТ Е ФЛАГЪТ, НЕ СТОЙНОСТТА. Изкушението е да се провери
        `if orderpoint.qty_multiple: continue`, но ядрото дава на полето **default
        1.0**, а не 0 — тоест такъв гард би прескачал посяването ВИНАГИ и модулът
        щеше да е тих no-op. (Това обяснява и защо на прода 43 orderpoint-а стоят
        на `1.00`: не е ничие решение, а ядреният подразбиращ се.)
        Затова единственият признак за „човек е решил" е `manual_qty_multiple_set`,
        който се вдига при изричен избор — в `create()` или в `write()`.
        """
        for orderpoint in self:
            if orderpoint.manual_qty_multiple_set:
                continue
            length_m = orderpoint._bar_length_for_seed()
            if not length_m:
                continue
            orderpoint.with_context(**{SEED_CTX: True}).qty_multiple = length_m
            _logger.info(
                "Orderpoint %s (%s): seeded qty_multiple = %s from full bar length.",
                orderpoint.id, orderpoint.product_id.display_name, length_m,
            )

    def _bar_length_for_seed(self):
        """Дължината на ЦЯЛ прът в мерната единица на продукта, или 0.

        🔴 САМО от пълни прътове. Остатъчните лотове (`is_offcut`) се раждат при
        ВСЯКА оптимизация на разкроя; посяването от тях би дало кратно от рода на
        2.3 м, което не е поръчваемо количество и би замърсило снабдяването с
        толкова правила, колкото разкроя е имало.

        Гардът е ВЪТРЕ в домейна, не проверка след намирането — така остатъчен лот
        не може да влезе дори по случайност.

        Чете се `bar_length_mm` („Standard length this bar lot represents"), НЕ
        `offcut_length_mm` — двете съществуват едновременно на модела и объркването
        им е тихо.
        """
        self.ensure_one()
        product = self.product_id
        if not product:
            return 0.0
        lot = self.env["stock.lot"].search(
            [
                ("product_id", "=", product.id),
                ("is_offcut", "=", False),
                ("bar_length_mm", ">", 0.0),
            ],
            order="id desc",
            limit=1,
        )
        if not lot:
            return 0.0
        # Лотът пази милиметри; продуктовата мерна единица за прътовете е метър.
        # Прътът е ~6000 mm → 6.0 м. Закръгляме по прецизността на UoM-а, за да не
        # родим кратно с плаваща опашка (6.000000001), което после чупи сравненията.
        return float_round(
            lot.bar_length_mm / 1000.0,
            precision_rounding=product.uom_id.rounding or 0.01,
        )

    # ------------------------------------------------------------------
    # Заключване на ръчния избор
    # ------------------------------------------------------------------
    def write(self, vals):
        """Пипне ли някой кратното отвън — вдигаме флага и повече не посяваме.

        Същият замисъл като `manual_lead_time_set`: веднъж решено от човек (или от
        покупна опаковка), стойността спира да следва автоматиката.
        """
        # Същото ограничение като в `create()`: нулата не заключва. Иначе
        # автоматика, която „изчиства" кратното, би затворила посяването завинаги.
        if vals.get("qty_multiple") and not self.env.context.get(SEED_CTX):
            vals = dict(vals, manual_qty_multiple_set=True)
        return super().write(vals)

    def action_reset_qty_multiple_to_bar(self):
        """Отключва кратното и го посява наново от пълния прът.

        Изходът от заключването е ИЗРИЧЕН, не страничен ефект — човек трябва да
        поиска връщането, вместо то да се случи при следващото преизчисление.
        """
        for orderpoint in self:
            orderpoint.with_context(**{SEED_CTX: True}).write({
                "manual_qty_multiple_set": False,
                "qty_multiple": 0.0,
            })
        self._seed_qty_multiple_from_bar_length()
        return True
