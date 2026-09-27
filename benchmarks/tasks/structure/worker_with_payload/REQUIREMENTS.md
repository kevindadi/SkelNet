# Requirements

R1. A main task starts a group of two workers. [U]
R2. Each worker takes a shared mutex, calls a sequential helper routine that performs only local computation, then updates a shared counter while still holding the mutex. [U]
R3. Each worker releases the mutex it took before it finishes. [U]
R4. At most one worker may hold the shared mutex at any moment.
R5. A worker that cannot take a held mutex waits until it becomes free.
R6. Every schedule and interleaving of the workers must terminate.
R7. Both workers complete.
R8. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2, compute.
- Shared resources: m (lock), acc (shared variable).
