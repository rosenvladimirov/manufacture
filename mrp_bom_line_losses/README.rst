===================
MRP BoM Line Losses
===================

This module adds a loss percentage to BoM lines.
When a production order is created, the quantity of the components is increased by the loss percentage defined in the BoM.

Configuration
=============

In any BoM line, fill the "Losses" field.

Usage
=====

1. Create a BoM with a component.
2. Set a loss percentage (e.g., 0.1 for 10%) on the BoM line.
3. Create a Manufacturing Order using this BoM.
4. The component quantity in the Manufacturing Order will be: BoM quantity * (1 + Loss).

Credits
=======

Authors
-------

* vladimirov.rosen@gmail.com
