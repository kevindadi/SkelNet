# Requirements

R1. A main task performs two start-and-wait cycles: it starts worker, waits for that worker to finish, and then repeats the cycle.
R2. The worker task performs no shared work and shares no mutexes or counters with the main task.
R3. Each started worker is waited for exactly once before the next worker is started.
R4. Every started worker must be able to complete under every possible schedule.
R5. Every schedule and interleaving must terminate.
R6. Count completed worker activations from their joined return values. The program must print exactly the line `DONE workers=2` and then exit.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): worker.
