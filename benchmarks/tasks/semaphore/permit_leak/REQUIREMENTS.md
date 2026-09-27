# Requirements

R1. The program starts a supervising task that launches two worker threads and waits for both of them to finish.
R2. Both worker threads share one counting permit pool that begins with exactly one permit.
R3. A worker must hold a permit while it performs its work, so the two workers never work at the same time.
R4. Each worker acquires one permit, performs its work, and must release that permit before it finishes.
R5. While a worker waits for the permit, the worker holding it must remain able to release it so the waiting worker can eventually proceed.
R6. Every possible schedule and interleaving of the two workers must terminate.
R7. The program must print exactly the line `DONE permits=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: s (semaphore).
