# Requirements

R1. A main task starts three transfer roles that run at the same time. [U]
R2. There are three accounts, each protected by its own lock, and an account may not be read or changed except while its lock is held.
R3. The first role moves one unit from the first account to the second, the second role moves one unit from the second account to the third, and the third role moves one unit from the third account to the first.
R4. A role must hold both the source account's lock and the destination account's lock at the same time while it moves its unit.
R5. The total number of units held across the three accounts is always three.
R6. In every state each account holds at least zero units and at most three units.
R7. The main task starts all three roles and only finishes after all three have finished.
R8. Every role must finish eventually, whatever order the roles run in.
R9. Every possible schedule or interleaving of the roles must terminate.
R10. The program must print exactly the line `DONE total=3` and then exit. The value is the sum of the three account balances at the end, not a constant written into the print. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): ab, bc, ca.
- Shared resources: a (lock), b (lock), c (lock).
