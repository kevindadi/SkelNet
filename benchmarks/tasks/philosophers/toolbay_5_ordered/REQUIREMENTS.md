# Requirements

R1. A main task starts five robot roles that run at the same time. [U]
R2. The five robots share five tool bays, and no bay may be occupied by more than one robot at a time.
R3. Each robot must occupy both of the bays it needs at the same time while it works.
R4. A robot that finds a bay busy must wait for it to become free and then continue.
R5. Every robot must claim its two bays in one global order that is the same for all five robots.
R6. The main task starts all five robots and only finishes after all five have finished.
R7. Every robot must release both bays before it finishes.
R8. It must never be possible for the robots to leave each other waiting forever, each holding one bay and needing another.
R9. Every possible schedule or interleaving of the five robots must terminate with all five finished.
R10. The program must print exactly the line `DONE sum=15` and then exit. The value is the sum of the ids the five robots return, not a constant written into the print. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): r1, r2, r3, r4, r5.
- Shared resources: bay0, bay1, bay2, bay3, bay4 (locks).
