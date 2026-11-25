/**
 * Чистите функции на „пусни тук“ (SPEC Р32, TECH_DESIGN §9.4): без DOM и без
 * сървър, за да се тестват отделно (Hoot Г2).
 *
 * Вагон = {id, start, stop, started}; `start`/`stop` са милисекунди, а
 * вагоните са подредени по начало (после по id). Клиентът смята по
 * стенния часовник — това е само подсказка на екрана; истината е M17 на
 * сървъра, който ходи по календара.
 */

/**
 * Подрежда вагоните по начало, после по id (като веригата на M17).
 *
 * @param {{id: number, start: number, stop: number, started?: boolean}[]} wagons
 */
export function sortWagons(wagons) {
    return [...wagons].sort((a, b) => a.start - b.start || a.id - b.id);
}

/**
 * Р32: веригата, която пускането избутва — вагоните от `k` нататък, които
 * призракът [start, start + duration) и избутаните пред тях застъпват; спира
 * на първата дупка (по стенния часовник — само подсказка на екрана).
 *
 * @returns {object[]} избутаните вагони по реда на веригата
 */
export function pushedChain(wagons, k, start, duration) {
    const chain = [];
    let cursor = start + duration;
    for (let j = k; j < wagons.length; j++) {
        const wagon = wagons[j];
        if (wagon.start >= cursor) {
            break;
        }
        chain.push(wagon);
        cursor += wagon.stop - wagon.start;
    }
    return chain;
}

/**
 * Р32: избутването тръгва от `start` с вагон с дължина `duration` пред
 * вагона `k` и бута следващите верижно; спира на първата дупка. Започнат
 * вагон по веригата блокира пускането.
 *
 * @returns {number | false} id на започнатия вагон, който спира пускането
 */
export function isBlockedByStarted(wagons, k, start, duration) {
    const started = pushedChain(wagons, k, start, duration).find((wagon) => wagon.started);
    return started ? started.id : false;
}

/**
 * Решението при влачене над писта.
 *
 * - `free`: призракът не застъпва нито един вагон — пуска се от T
 *   (`dateStart`), без `after`;
 * - `insert`: застъпва — k = броят вагони, чиято среда е преди началото на
 *   призрака; пуска се след вагон k-1 (`afterId`), а при k = 0 — от
 *   min(T, началото на първия);
 * - `blocked`: веригата стига до започнат вагон (Р32).
 *
 * Застъпването и k се смятат по това, което планиращият ВИЖДА (дефект от
 * живия тест 09.10, 19.0.1.6.1): с `grid` — по колоните на Ганта
 * (`grid` = [начало, край) на призрака, всеки вагон носи `col` = [начало,
 * край)). При едра клетка (половин ден) T пази часа на влачената поръчка и
 * може да падне в нощта, докато призракът покрива вагона — по часовете
 * тогава излиза `free` и стрелка няма. Без `grid` — по часовете (както
 * досега). `dateStart`, `afterId` и блокирането са винаги по часовете.
 *
 * @param {{id: number, start: number, stop: number, started?: boolean, col?: number[]}[]} wagons
 * @param {number} start T, началото на призрака (ms)
 * @param {number} duration дължината на влачената поръчка (ms)
 * @param {number[] | null} [grid] колоните на призрака [начало, край)
 */
export function computeInsertion(wagons, start, duration, grid = null) {
    const sorted = sortWagons(wagons);
    const span = (wagon) => (grid ? wagon.col : [wagon.start, wagon.stop]);
    const [ghostStart, ghostStop] = grid || [start, start + duration];
    const overlaps = sorted.some((wagon) => {
        const [wagonStart, wagonStop] = span(wagon);
        return wagonStart < ghostStop && ghostStart < wagonStop;
    });
    if (!overlaps) {
        return {
            mode: "free",
            k: sorted.filter((wagon) => span(wagon)[1] <= ghostStart).length,
            afterId: false,
            dateStart: start,
            blocked: false,
            blockerId: false,
            pushedIds: [],
            wagons: sorted,
        };
    }
    const k = sorted.filter((wagon) => {
        const [wagonStart, wagonStop] = span(wagon);
        return (wagonStart + wagonStop) / 2 < ghostStart;
    }).length;
    const afterId = k > 0 ? sorted[k - 1].id : false;
    const dateStart = k === 0 ? Math.min(start, sorted[0].start) : null;
    const newStart = k > 0 ? sorted[k - 1].stop : dateStart;
    const blockerId = isBlockedByStarted(sorted, k, newStart, duration);
    return {
        mode: "insert",
        k,
        afterId,
        dateStart,
        blocked: Boolean(blockerId),
        blockerId,
        pushedIds: pushedChain(sorted, k, newStart, duration).map((wagon) => wagon.id),
        wagons: sorted,
    };
}
