# Requirements

R1. A main task starts a group of two workers.
R2. Each worker takes the shared mutex m, calls compute for one unit of sequential local work, then adds that result to acc while still holding m. The shared counter acc starts at zero.
R3. Each worker releases the mutex it took before it finishes.
R4. At most one worker may hold the shared mutex at any moment.
R5. A worker that cannot take a held mutex waits until it becomes free.
R6. Every schedule and interleaving of the workers must terminate.
R7. Both workers complete.
R8. After both workers finish, report the final shared counter. The program must print exactly the line `DONE acc=2` and then exit.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2, compute.
- Shared resources: m (lock), acc (shared variable).
