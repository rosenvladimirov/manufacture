/**
 * Неработното време в Ганта „Планирай център“ (№142 на Теолино).
 *
 * Гантът на EE е решетка с еднакви подколони и сметката колона ↔ дата е
 * аритметична на десетки места (лентите, влаченето, разтягането, линията
 * „сега“). Затова времевата ос не се преподрежда: неработните подколони
 * остават в логическата решетка, но шаблонът на CSS решетката им дава
 * НУЛЕВА ширина. Лента през нощта изглежда непрекъсната, курсорът не може
 * да спре в неработно време, а заглавката на изцяло почивен ден изчезва.
 *
 * Общата ос: скрива се подколона, неработна за ВСИЧКИ показани центрове.
 * Неработното само за един център остава сиво на неговия ред (Г3).
 *
 * Скрива се цяла подколона: в мащаб „ден“ (час / 30 / 15 мин) — нощите и
 * почивките; в „седмица“ и „месец“ подколоната е половин ден ⇒ само изцяло
 * неработните половини (почивни дни, празници). Часови подколони там
 * променят решението на стрелката (Г3c, тур 36) — отделно решение.
 */

/**
 * Дали интервалите покриват изцяло [start, stopExclusive).
 *
 * @param {Array<{start: DateTime, stop: DateTime}>} intervals сортирани по start
 */
export function crewCovered(intervals, start, stopExclusive) {
    let cursor = start;
    for (const interval of intervals) {
        if (interval.stop <= cursor) {
            continue;
        }
        if (interval.start > cursor) {
            return false;
        }
        cursor = interval.stop;
        if (cursor >= stopExclusive) {
            return true;
        }
    }
    return cursor >= stopExclusive;
}

/**
 * Номерата на подколоните, неработни за всички показани центрове.
 *
 * @param {Array<{col: number, start: DateTime, stop: DateTime}>} subColumns
 *        `stop` е включително (последната секунда, както в `makeSubColumn`)
 * @param {Array<Array<{start: DateTime, stop: DateTime}>>} unavailabilities
 *        по един списък на център; център без неработно време = празен списък
 * @returns {Set<number>}
 */
export function crewHiddenCols(subColumns, unavailabilities) {
    const hidden = new Set();
    if (!unavailabilities.length) {
        return hidden;
    }
    const sorted = unavailabilities.map((list) => [...list].sort((a, b) => a.start - b.start));
    for (const sub of subColumns) {
        const stopExclusive = sub.stop.plus({ seconds: 1 });
        if (sorted.every((list) => crewCovered(list, sub.start, stopExclusive))) {
            hidden.add(sub.col);
        }
    }
    return hidden;
}

/**
 * Шаблонът на колоните на решетката: участък само от скрити подколони е
 * `0px`, останалите — както в EE (`minmax(<ширина>,1fr)`), с ширина по
 * видимите подколони. `keys` са границите на участъците (сортирани).
 */
export function crewColsTemplate(keys, hidden, cellPartWidth) {
    const template = [];
    for (let i = 0; i < keys.length - 1; i++) {
        const x = +keys[i];
        const y = +keys[i + 1];
        let visible = 0;
        for (let col = x; col < y; col++) {
            if (!hidden.has(col)) {
                visible++;
            }
        }
        template.push(visible ? `[c${x}]minmax(${visible * cellPartWidth}px,1fr)` : `[c${x}]0px`);
    }
    template.push(`[c${keys.at(-1)}]`);
    return template.join("");
}
