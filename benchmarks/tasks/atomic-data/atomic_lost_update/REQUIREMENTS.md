# Requirements

R1. The program starts a supervising task that launches two worker threads and waits for both of them to finish.
R2. Both worker threads share a single atomic counter that starts at zero.
R3. Each worker adds exactly one to the shared counter, so once both have finished the counter equals two.
R4. Each worker updates the counter with an atomic read-modify-write retry loop, so a competing update can never be silently lost.
R5. A failed update attempt must be retried rather than abandoned, so every worker's increment eventually takes effect.
R6. From every state that can occur, it must remain possible for the counter to still reach two.
R7. Each increment appears to happen in a single indivisible step, so no partial update is ever observable.
R8. Every possible schedule and interleaving of the two workers must terminate.
R9. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: c (atomic counter).
