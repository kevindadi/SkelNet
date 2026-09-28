# Requirements

R1. The program starts a supervising task that launches two worker threads and waits for both of them to finish.
R2. Both worker threads share one counting permit pool that begins with exactly one permit.
R3. A worker must hold a permit while it performs its work, so the two workers never work at the same time.
R4. Each worker may acquire the permit more than once, and on every path it must release the permit exactly as many times as it acquired it before it finishes.
R5. While a worker waits for a permit, the worker currently holding it must remain able to release it so the waiting worker can eventually proceed.
R6. Every possible schedule and interleaving of the two workers must terminate.
R7. The program must print exactly the line `DONE w1=2 w2=1` and then exit. w1 completes the acquire-and-release pair twice and w2 completes it once. Each number is that worker's completion count, returned after those pairs, not a constant written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: s (semaphore).
