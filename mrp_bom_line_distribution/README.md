# MRP BoM Line Distribution

Manage distribution coefficients on BoM lines and carry them into production orders.

## Features

- Adds a main component on BoM lines with a 100% distribution coefficient.
- Adds a base material quantity on the BoM used to compute line quantities.
- Adjusts the master line coefficient automatically when other lines change.
- Computes line quantities as `base_qty * coefficient`.
- Carries coefficients and base quantity into production raw material moves.
- Allows editing coefficients on production moves and recomputes planned quantities.
- Logs each coefficient change on production moves with a weighted average.
- Extends BoM Structure report and BoM Overview with coefficient columns.

## Usage

1) Open a BoM and set **Main Component** and **Base Material Qty**.
2) Add component lines and set **Distribution Coefficient**.
3) The master line is kept at the remaining coefficient and updated quantity.
4) Create a Manufacturing Order to see coefficients on raw material moves.
5) Update the coefficient on a move to recompute planned quantity.
6) Use the history icon to view the coefficient log.

## Technical notes

- Master line is created with sequence 0.
- Coefficients are stored as 0-1 ratio (percentage in the UI).
- Production move logs use weighted average by planned quantity.

## License

AGPL-3.0 or later.
