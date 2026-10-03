# Requirements

R1. A main task starts four philosopher roles that run at the same time. [U]
R2. The four philosophers share four forks, and no fork may be held by more than one philosopher at a time.
R3. Each philosopher must hold both of the forks beside it at the same time while it eats.
R4. A philosopher that finds a fork busy must wait for it to become free and then continue.
R5. At most three philosophers may hold forks at the same time, so a philosopher must take a seat from the waiter before it picks up any fork.
R6. The main task starts all four philosophers and only finishes after all four have finished.
R7. Every philosopher must release both forks and its seat before it finishes.
R8. It must never be possible for the philosophers to leave each other waiting forever, each holding one fork and needing another.
R9. Every possible schedule or interleaving of the four philosophers must terminate with all four finished.
R10. The program must print exactly the line `DONE sum=10` and then exit. The value is the sum of the ids the four philosophers return, not a constant written into the print. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): p1, p2, p3, p4.
- Shared resources: f0, f1, f2, f3 (locks), waiter (semaphore).
