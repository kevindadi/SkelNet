# Requirements

R1. A main task starts a group of two workers that both contend for the same two mutexes, A and B. [U]
R2. Each worker takes mutex A and mutex B and, at some point, holds both of them at the same time.
R3. Each worker releases each mutex it took once its work is finished. [U]
R4. At most one worker may hold a given mutex at any moment.
R5. The two workers take the mutexes in the same order so that no wait cycle can form.
R6. A worker that cannot take a held mutex waits until it becomes free.
R7. Every schedule and interleaving of the workers must terminate.
R8. Each worker completes, and the group finishes only after both workers have completed.
R9. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2.
- Shared resources: a (lock), b (lock).
