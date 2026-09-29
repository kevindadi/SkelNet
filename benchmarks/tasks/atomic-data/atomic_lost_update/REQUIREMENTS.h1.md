# Requirements

R1. The program starts a supervising task that launches two worker threads and waits for both of them to finish.
R2. Both worker threads share a single atomic counter that starts at zero.
R3. Each worker adds exactly one to the shared counter, so once both have finished the counter equals two.
R4. Competing updates must preserve both workers' contributions to the counter.
R5. Every worker's increment must eventually take effect, including when both workers attempt to update the counter concurrently.
R6. From every state that can occur, it must remain possible for the counter to still reach two.
R7. Each increment appears to happen in a single indivisible step, so no partial update is ever observable.
R8. Every possible schedule and interleaving of the two workers must terminate.
R9. After both workers finish, report the final shared counter. The program must print exactly the line `DONE c=2` and then exit.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: c (atomic counter).
