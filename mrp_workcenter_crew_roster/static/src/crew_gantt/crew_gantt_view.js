import { registry } from "@web/core/registry";
import { mrpWorkorderGanttView } from "@mrp_workorder/mrp_workorder_gantt_view";
import { CrewGanttArchParser } from "./crew_gantt_arch_parser";
import { CrewGanttController } from "./crew_gantt_controller";
import { CrewGanttModel } from "./crew_gantt_model";
import { CrewGanttRenderer } from "./crew_gantt_renderer";

/**
 * `js_class="mrp_crew_gantt"`: Гантът „Планирай център“ (TECH_DESIGN §4,
 * §9.4). Парсерът оставя само ръчния режим (С14): местенето е стрелката.
 */
export const mrpCrewGanttView = {
    ...mrpWorkorderGanttView,
    ArchParser: CrewGanttArchParser,
    Controller: CrewGanttController,
    Model: CrewGanttModel,
    Renderer: CrewGanttRenderer,
    buttonTemplate: "mrp_workcenter_crew_roster.CrewGanttView.Buttons",
};

registry.category("views").add("mrp_crew_gantt", mrpCrewGanttView);
