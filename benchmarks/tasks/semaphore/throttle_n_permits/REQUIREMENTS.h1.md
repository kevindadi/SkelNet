# Requirements

R1. The program starts a supervising task that launches three worker threads and waits for all of them to finish.
R2. All three worker threads share one counting permit pool that begins with exactly two permits.
R3. Each worker acquires one permit, performs its work, releases the permit, and then finishes.
R4. At most two workers may hold permits at the same time, so a third worker waits until a permit is released.
R5. A worker that is waiting for a permit must eventually obtain one.
R6. Every possible schedule and interleaving of the three workers must terminate.
R7. The program must print exactly the line `DONE w1=1 w2=1 w3=1` and then exit. Each worker adds one to its own completion count while it holds a permit. The three numbers are those counts, returned by the workers, not constants written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2, w3.
- Shared resources: s (semaphore).
