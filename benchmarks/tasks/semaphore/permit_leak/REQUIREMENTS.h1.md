# Requirements

R1. The program starts a supervising task that launches two worker threads and waits for both of them to finish.
R2. Both worker threads share one counting permit pool that begins with exactly one permit.
R3. A worker must hold a permit while it performs its work, so the two workers never work at the same time.
R4. Each worker acquires one permit, performs its work, and must release that permit before it finishes.
R5. A worker that is waiting for a permit must eventually obtain one.
R6. Every possible schedule and interleaving of the two workers must terminate.
R7. The program must print exactly the line `DONE permits=1` and then exit. After both workers have finished, the program counts how many permits can be taken without blocking and prints that count. The pool starts with one permit and both workers release what they acquire, so the count is that remaining size.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: s (semaphore).
