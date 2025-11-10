# Dynamic BOM for Lots/Serial Numbers - Documentation

## General Information

### Purpose
The module allows creating specific Bills of Materials (BOMs) for individual lots/serial numbers of products. This is useful when the same product can be manufactured with different material quantities depending on the specification of a particular order or batch.

### Key Features
- ✅ Create specific BOMs for individual lots
- ✅ Automatically load components from master recipe
- ✅ Adjust material quantities for specific lots
- ✅ Track differences from standard BOM
- ✅ Organize materials by production stages
- ✅ Automatically apply adjusted quantities during production

---

## Use Cases

### 1. **Make-to-Order Production**
When customers order products with different specifications (e.g., windows with different sizes), each lot can have its own BOM with exact quantities of glass, profiles, and hardware.

### 2. **Batch Production with Variants**
In furniture manufacturing, where the same models can be produced with different materials or finishes depending on the batch.

### 3. **Quality Control**
Track exactly which materials and in what quantities were used for production of a specific lot, important for analysis in case of complaints.

### 4. **Material Optimization**
Reduce waste by precisely defining the required quantities for each batch.

---

## Module Structure

### Models

#### 1. **mrp.bom.line** (Extension)
```
Added fields:
- lot_dynamic: Boolean - Marks whether the component can have different quantities per lot
```

#### 2. **mrp.bom.lot** (New Model)
```
Main fields:
- name: Reference (automatic sequence)
- product_tmpl_id: Product template
- product_id: Specific product
- master_bom_id: Master recipe (base)
- lot_id: Lot/Serial batch
- lot_name: Lot name (if doesn't exist yet)
- line_ids: Components (One2many to mrp.bom.lot.line)
- product_qty: Quantity
- state: Status (draft/confirmed/done/cancel)
```

#### 3. **mrp.bom.lot.line** (New Model)
```
Main fields:
- bom_lot_id: Link to BOM for lot
- master_bom_line_id: Original line from master BOM
- product_id: Component
- product_qty: Quantity (adjusted)
- stage_id: Production stage
- master_product_qty: Quantity from master BOM (computed)
- qty_difference: Difference from master BOM (computed)
```

#### 4. **mrp.bom.stage** (New Model)
```
Main fields:
- name: Stage name
- sequence: Sequence
- code: Identification code
- is_common: Common stage (for materials without specific stage)
```

#### 5. **mrp.production** (Extension)
```
Added fields:
- bom_lot_id: BOM specific to the lot
```

---

## Workflow

### Step 1: Prepare Master BOM

1. Create a standard BOM for the product (mrp.bom)
2. For each component that can vary by lot, mark **"Lot Dynamic" = True**

**Example:**
```
Product: Window 120x150cm
Components:
- PVC Profile (Lot Dynamic: ✓) - 5.4 m
- Glass (Lot Dynamic: ✓) - 1.8 m²
- Hardware (Lot Dynamic: ✗) - 12 pcs
```

### Step 2: Create BOM for Lot

1. Open **Manufacturing → Configuration → BOM for Lots**
2. Click **Create**
3. Fill in:
   - **Product template**: Select the product
   - **Product variant**: (if variants exist)
   - **Master BOM**: Select the master recipe
   - **Lot/Serial Number**: Select existing lot OR
   - **Lot/Serial Name**: Enter name for new lot

4. Click the **"Load from Master BOM"** button
   - All components marked as "Lot Dynamic" will be automatically loaded

### Step 3: Adjust Quantities

1. In the **Components** table you will see:
   - **Component**: Component name
   - **Quantity**: Current quantity (you can edit)
   - **Quantity (Master BOM)**: Standard quantity
   - **Difference**: Automatically calculated difference
   - **Stage**: Production stage (optional)

2. Change quantities according to the specification

**Example:**
```
Lot: WIN-2024-001
Specification: Window 100x150cm (narrower than standard)

Components:
- PVC Profile: 5.0 m (instead of 5.4 m) | Difference: -0.4 m
- Glass: 1.5 m² (instead of 1.8 m²) | Difference: -0.3 m²
```

### Step 4: Confirmation

1. Click the **"Confirm"** button
2. Status changes to **"Confirmed"**
3. BOM is ready for use in production

### Step 5: Production with Lot BOM

#### Option A: Automatic Loading

1. Create a Manufacturing Order
2. Select the product
3. In the **"Lot/Serial Number"** field, select the lot
4. System will automatically find the confirmed BOM for this lot and show a warning

#### Option B: Manual Loading

1. Create a Manufacturing Order
2. Select the product and lot
3. In the **"BOM for Lot/Serial number"** field, select the corresponding BOM
4. Click the **"Load Lot BOM"** button
5. Material quantities will be automatically adjusted
6. Lot BOM is automatically marked as **"Used"**

---

## Production Stages

### Creating Stages

1. Open **Manufacturing → Configuration → BOM Stages**
2. Create stages like:
   - **Cutting** (sequence: 10)
   - **Sanding** (sequence: 20)
   - **Assembly** (sequence: 30)
   - **Finishing** (sequence: 40)

3. Mark one stage as **"General stage"** for materials without a specific stage

### Usage

When adjusting components in the lot BOM, you can specify which stage each component belongs to. This facilitates organization during production.

---

## View from Lots

1. Open **Inventory → Products → Lots/Serial Numbers**
2. Select a lot
3. You will see a button/option for **"View BOM lots"**
4. All BOMs created for this lot are displayed

---

## Lot BOM States

| State | Description | Actions |
|-----------|----------|----------|
| **Draft** | Draft, editable | You can edit everything |
| **Confirmed** | Confirmed, ready for use | Can be used in production |
| **Used** | Used | Automatically after application in production |
| **Cancel** | Cancelled | Inactive BOM |

---

## Useful Tips

### 💡 Tip 1: Organization
Use a clear naming convention for lots, for example:
- `WIN-2024-001` (Window, year, number)
- `CLIENT-ORDER-LOT` (Client, order, lot)

### 💡 Tip 2: Stages
Define stages according to your production process. This helps with material planning.

### 💡 Tip 3: Tracking
Always confirm the lot BOM before starting production to avoid errors.

### 💡 Tip 4: Analysis
Use the "Difference" field to analyze material optimization - positive differences mean more material, negative - less.

### 💡 Tip 5: Documentation
Use the "Comment" field for additional information - reason for change, specific customer requirements, etc.

---

## Advantages

✅ **Precision** - Exact quantities for each lot  
✅ **Flexibility** - Easy adaptation to different specifications  
✅ **Traceability** - Complete history for each produced lot  
✅ **Optimization** - Reduction of waste and costs  
✅ **Automation** - Automatic application during production  
✅ **Control** - Visible differences from standard  

---

## Technical Requirements

- **Odoo version**: 16/17/18
- **Module dependencies**: `mrp`, `stock`
- **Sequence**: `mrp.bom.lot` must be configured

---

## Frequently Asked Questions

**Q: Can I change the lot BOM after confirmation?**  
A: Not directly. You need to return it to draft, make changes, and confirm again.

**Q: What happens if I don't mark a component as "Lot Dynamic"?**  
A: It won't be automatically loaded into the lot BOM and the standard quantity from the master BOM will be used.

**Q: Can I have multiple BOMs for one lot?**  
A: Yes, but only one can be confirmed and active at a time.

**Q: What happens to the lot BOM after use?**  
A: It's automatically marked as "Used" and remains for reference and traceability.

**Q: How do I add new components that are not in the master BOM?**  
A: Currently, the module doesn't support adding completely new components. All components must be defined in the master BOM and marked as "Lot Dynamic".

**Q: Can I use the module without creating stages?**  
A: Yes, stages are optional and serve only for better organization.

---

## Practical Example Scenario

### Example: Window Production

**Situation:**  
A PVC window manufacturing company receives an order for 10 windows with non-standard dimensions.

**Standard BOM:**
```
Product: PVC Window standard (140x150 cm)
- PVC Profile 6m: 6.0 m (Lot Dynamic: ✓)
- Double glazing: 2.1 m² (Lot Dynamic: ✓)
- Handle: 1 pcs (Lot Dynamic: ✗)
- Hardware kit: 1 set (Lot Dynamic: ✗)
```

**Special Order:**
```
Lot: WIN-CLIENT-A-2024-15
Size: 120x140 cm (smaller than standard)

BOM for lot:
- PVC Profile 6m: 5.2 m (saving -0.8 m)
- Double glazing: 1.68 m² (saving -0.42 m²)
- Handle: 1 pcs (standard)
- Hardware kit: 1 set (standard)
```

**Result:**
- Exact quantities for the order
- Reduced material waste
- Complete traceability for the client
- Correct cost calculation

---

## Process Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         WORKFLOW                                 │
└─────────────────────────────────────────────────────────────────┘

   [Master BOM]                    [New Order]
         │                                │
         │                                │
         ├────────────────────────────────┤
         │                                │
         ▼                                ▼
   ┌──────────────────────────────────────────┐
   │  Create BOM for Lot                      │
   │  - Select Master BOM                     │
   │  - Define lot                            │
   └──────────────────────────────────────────┘
                    │
                    ▼
   ┌──────────────────────────────────────────┐
   │  Automatically load components           │
   │  (only Lot Dynamic = True)               │
   └──────────────────────────────────────────┘
                    │
                    ▼
   ┌──────────────────────────────────────────┐
   │  Adjust quantities                       │
   │  - Manual entry                          │
   │  - Automatic difference calculation      │
   └──────────────────────────────────────────┘
                    │
                    ▼
   ┌──────────────────────────────────────────┐
   │  Confirmation (State = Confirmed)        │
   └──────────────────────────────────────────┘
                    │
                    ▼
   ┌──────────────────────────────────────────┐
   │  Create Manufacturing Order              │
   │  - Automatic detection of lot BOM        │
   └──────────────────────────────────────────┘
                    │
                    ▼
   ┌──────────────────────────────────────────┐
   │  Apply quantities                        │
   │  (State = Used)                          │
   └──────────────────────────────────────────┘
                    │
                    ▼
            [Production]
```

---

## Compatibility and Limitations

### Compatibility
- ✅ Odoo 16, 17, 18
- ✅ Community and Enterprise editions
- ✅ Works with multi-company settings
- ✅ Compatible with standard MRP modules

### Known Limitations
- ⚠️ Cannot add components outside the master BOM
- ⚠️ One lot can have only one active (confirmed) BOM at a time
- ⚠️ After use (state=done), BOM cannot be changed
- ⚠️ Requires sequence configuration for automatic numbering

---

## Maintenance and Extensions

### Possible Extensions
1. **Automatic Calculation** - Based on formulas (e.g., perimeter × coefficient)
2. **Import/Export** - Bulk creation of lot BOMs from Excel
3. **Reports** - Analysis of differences by lot, waste tracking
4. **CAD Integration** - Automatic calculation from drawings
5. **Approvals** - Workflow for BOM approval before confirmation

### Contact
For technical questions, consultations, or module development, contact your Odoo integrator.

---

**Documentation version:** 1.0  
**Last update:** November 2024  
**License:** In accordance with Odoo license  

---

## Appendix: Sample XML Views (for developers)

### Tree View for mrp.bom.lot
```xml
<tree string="BOM for Lots">
    <field name="name"/>
    <field name="product_tmpl_id"/>
    <field name="lot_id"/>
    <field name="master_bom_id"/>
    <field name="product_qty"/>
    <field name="state"/>
</tree>
```

### Form View Buttons
```xml
<header>
    <button name="action_load_from_master" 
            string="Load from Master BOM" 
            type="object" 
            class="oe_highlight"
            states="draft"/>
    <button name="action_confirm" 
            string="Confirm" 
            type="object" 
            class="oe_highlight"
            states="draft"/>
    <button name="action_cancel" 
            string="Cancel" 
            type="object"
            states="draft,confirmed"/>
    <button name="action_draft" 
            string="Set to Draft" 
            type="object"
            states="cancel"/>
</header>
```

---

## Acknowledgments

This module was developed to optimize production processes in Odoo and adapt to the specific needs of Bulgarian market manufacturing companies.

