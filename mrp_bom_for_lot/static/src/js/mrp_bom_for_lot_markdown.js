/** @odoo-module **/

import { markdownRegistry } from "@markdown_viewer_locale/js/markdown_registry";

// Регистрираме документацията за ДДС администрация
markdownRegistry.register(
    'mrp_bom_for_lot',
    'mrp_bom_for_lot',
    'bom_lots_documentation.md',
    'Guide to BOM Lots (Manufacture)',
    'Manufacture',
    'Complete guide to using the module for managing BOM lots in manufacturing processes',
    [
        'mrp.bom',
        'mrp.bom.line',
        'mrp.bom.lot',
        'mrp.bom.stage',
        'mrp.production',
        'mrp.production.lot'
    ]
);

console.log("✅ BOM Lots documentation registered successfully!");
