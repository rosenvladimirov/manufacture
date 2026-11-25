import { _t } from "@web/core/l10n/translation";
import { GanttArchParser } from "@web_gantt/gantt_arch_parser";

/**
 * Парсерът на Ганта „Планирай център“ (TECH_DESIGN §9.4, Г6, С14): копие на
 * стандартния, но режимът на препланиране е само „ръчен“. Автоматичните
 * режими на EE местят по зависимостите без писти; в Ганта с писти
 * местенето е стрелката „пусни тук“ (M17). Без глобален `patch`.
 */
export class CrewGanttArchParser extends GanttArchParser {
    parse(arch) {
        const archInfo = super.parse(arch);
        archInfo.rescheduleMethods = { manual: _t("Manual Reschedule") };
        archInfo.defaultRescheduleMethod = "manual";
        return archInfo;
    }
}
