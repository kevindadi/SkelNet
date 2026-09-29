# Requirements

R1. A main task starts three worker roles, w1, w2, and w3, with one activation each sharing a single permit. Each role allows at most two simultaneous activations.
R2. Each activation holds the single permit while completing one unit of work and releases it afterwards.
R3. At most one activation may hold the permit at any moment.
R4. An activation that cannot obtain the permit waits until the permit becomes available.
R5. Every schedule and interleaving must terminate.
R6. All three worker roles complete.
R7. Sum completed work units from the three joined worker results. The program must print exactly the line `DONE completed=3` and then exit.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2, w3.
- Shared resources: s (semaphore).
