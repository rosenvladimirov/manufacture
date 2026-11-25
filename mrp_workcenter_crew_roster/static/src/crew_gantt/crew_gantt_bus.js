import { useEffect } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/** Низът, който сървърът превежда в защитения канал (фирма, "mrp_crew_lane") — С3. */
export const CREW_LANE_CHANNEL = "mrp_crew_lane";
/** Видовете съобщения (С4). */
export const CREW_BUS_DRAG = "mrp_crew_lane/drag";
export const CREW_BUS_LOCKED = "mrp_crew_lane/locked";
export const CREW_BUS_RELEASED = "mrp_crew_lane/released";
export const CREW_BUS_CHANGED = "mrp_crew_lane/changed";
/** Отлагането на презареждането при `changed` (ms). */
export const CREW_CHANGED_DEBOUNCE = 500;

/**
 * Шината на Ганта с писти (SPEC Р38, TECH_DESIGN §9.4, С3–С5).
 *
 * - `addChannel("mrp_crew_lane")` при монтиране, `deleteChannel` при
 *   демонтиране; сървърът го превежда в канал по фирма (M20);
 * - собственият раздел (`tab`) се пропуска;
 * - `drag`/`locked` заключват пистата, `released` я отключва, а
 *   изтичането без `released` го маха локален таймер;
 * - `changed` → `fetchData` с отлагане 500 ms, отложено, докато трае
 *   влачене (Г8: по време на влачене данните не се сменят).
 *
 * Логиката на реакцията е в рендерера (`crewOnBus*`); тук е само
 * абонаментът.
 *
 * @param {import("./crew_gantt_renderer").CrewGanttRenderer} renderer
 */
export function useCrewGanttBus(renderer) {
    const bus = renderer.env.services.bus_service;
    if (!bus) {
        return;
    }
    const handlers = {
        [CREW_BUS_DRAG]: (payload) => renderer.crewOnBusDrag(payload),
        [CREW_BUS_LOCKED]: (payload) => renderer.crewOnBusLocked(payload),
        [CREW_BUS_RELEASED]: (payload) => renderer.crewOnBusReleased(payload),
        [CREW_BUS_CHANGED]: (payload) => renderer.crewOnBusChanged(payload),
    };
    useEffect(
        () => {
            for (const [type, handler] of Object.entries(handlers)) {
                bus.subscribe(type, handler);
            }
            bus.addChannel(CREW_LANE_CHANNEL);
            return () => {
                for (const [type, handler] of Object.entries(handlers)) {
                    bus.unsubscribe(type, handler);
                }
                bus.deleteChannel(CREW_LANE_CHANNEL);
            };
        },
        () => []
    );
}

/**
 * Отлагане с възможност за изчакване, докато трае влачене: `trigger()`
 * насрочва `callback` след `delay`; ако в момента `isBusy()` е вярно,
 * извикването се пази и се прави от `flush()`.
 */
export class CrewDeferredCall {
    constructor(callback, delay, isBusy) {
        this.callback = callback;
        this.delay = delay;
        this.isBusy = isBusy;
        this.timeout = null;
        this.pending = false;
    }

    trigger() {
        browser.clearTimeout(this.timeout);
        this.timeout = browser.setTimeout(() => {
            this.timeout = null;
            if (this.isBusy()) {
                this.pending = true;
            } else {
                this.pending = false;
                this.callback();
            }
        }, this.delay);
    }

    flush() {
        if (this.pending && !this.isBusy()) {
            this.pending = false;
            this.callback();
        }
    }

    cancel() {
        browser.clearTimeout(this.timeout);
        this.timeout = null;
        this.pending = false;
    }
}
