# Requirements

R1. A main task starts a group of two workers that both contend for the same two mutexes, A and B.
R2. Each worker takes mutex A and mutex B, holds both at the same time, and increments each mutex-protected counter once. Both counters start at zero.
R3. Each worker releases each mutex it took once its work is finished.
R4. At most one worker may hold a given mutex at any moment.
R5. Every possible schedule must terminate; no worker may wait forever.
R6. A worker that cannot take a held mutex waits until it becomes free.
R7. Every schedule and interleaving of the workers must terminate.
R8. Each worker completes, and the group finishes only after both workers have completed.
R9. After both workers finish, report the final protected counters. The program must print exactly the line `DONE a=2 b=2` and then exit.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: a (lock), b (lock).
