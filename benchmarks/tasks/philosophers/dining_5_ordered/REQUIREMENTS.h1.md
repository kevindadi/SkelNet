# Requirements

R1. A main task starts five philosopher roles that run at the same time.
R2. The five philosophers share five forks, and no fork may be held by more than one philosopher at a time.
R3. Each philosopher must hold both of the forks beside it at the same time while it eats.
R4. A philosopher that finds a fork busy must wait for it to become free and then continue.
R5. Every philosopher must take its two forks in one global order that is the same for all five philosophers.
R6. The main task starts all five philosophers and only finishes after all five have finished.
R7. Every philosopher must release both forks before it finishes.
R8. It must never be possible for the philosophers to leave each other waiting forever, each holding one fork and needing another.
R9. Every possible schedule or interleaving of the five philosophers must terminate with all five finished.
R10. The program must print exactly the line `DONE sum=15` and then exit. The value is the sum of the ids the five philosophers return, not a constant written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): p1, p2, p3, p4, p5.
- Shared resources: f0, f1, f2, f3, f4 (locks).
