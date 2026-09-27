# Requirements

R1. The program starts a supervising task that launches two worker threads and waits for both of them to finish.
R2. Both worker threads share a single integer counter that is declared to range from zero to two and starts at zero.
R3. Each worker adds one to the shared counter only when doing so keeps the value within the required upper limit.
R4. A worker must hold the mutual-exclusion lock whenever it reads or writes the shared counter, so the two workers never update it at the same time.
R5. In every state that can occur, the counter never exceeds one, even though its declared range allows up to two.
R6. Every possible schedule and interleaving of the two workers must terminate.
R7. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: m (lock), c (shared variable).
