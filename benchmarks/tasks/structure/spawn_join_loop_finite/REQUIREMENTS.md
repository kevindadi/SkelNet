# Requirements

R1. A main task starts a worker task and waits for that worker to finish, then begins the same start-and-wait cycle again. [U]
R2. The worker task performs no shared work and shares no mutexes or counters with the main task. [U]
R3. Each started worker is waited for exactly once before the next worker is started.
R4. No task ever waits for a worker that cannot finish, so no execution stalls.
R5. Every schedule and interleaving must terminate.
R6. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): worker.
