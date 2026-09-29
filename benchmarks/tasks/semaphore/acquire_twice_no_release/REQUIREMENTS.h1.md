# Requirements

R1. The program starts a supervising task that launches two worker threads and waits for both of them to finish.
R2. Both worker threads share one counting permit pool that begins with exactly one permit.
R3. A worker must hold a permit while it performs its work, so the two workers never work at the same time.
R4. Each worker may acquire the permit more than once, and on every path it must release the permit exactly as many times as it acquired it before it finishes.
R5. A worker that is waiting for a permit must eventually obtain one.
R6. Every possible schedule and interleaving of the two workers must terminate.
R7. The program must print exactly the line `DONE w1=2 w2=1` and then exit. w1 acquires the permit two times in total and w2 acquires it once. Each number is how many acquisitions that worker completed, counted by the worker itself and returned to main when it finishes, not a constant written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: s (semaphore).
