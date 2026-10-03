# Requirements

R1. A main task starts three shipping roles that run at the same time.
R2. There are three warehouses, each with its own dock lock, and a warehouse's stock may not be read or changed except while its dock lock is held.
R3. The first role ships one crate from the first warehouse to the second, the second role ships one crate from the second warehouse to the third, and the third role ships one crate from the third warehouse to the first.
R4. A role must hold both the source warehouse's dock lock and the destination warehouse's dock lock at the same time while it ships its crate.
R5. The total number of crates held across the three warehouses is always three.
R6. In every state each warehouse holds at least zero crates and at most three crates.
R7. The main task starts all three roles and only finishes after all three have finished.
R8. Every role must finish eventually, whatever order the roles run in.
R9. Every possible schedule or interleaving of the roles must terminate.
R10. The program must print exactly the line `DONE crates=3` and then exit. The value is the sum of the three warehouse stock counts at the end, not a constant written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): ship_ns, ship_sw, ship_wn.
- Shared resources: north (lock), south (lock), west (lock).
