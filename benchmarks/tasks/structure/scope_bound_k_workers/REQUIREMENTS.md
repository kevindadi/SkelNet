# Requirements

R1. A main task starts three worker roles that share a single permit, and each role may have up to two activations running at once. [U]
R2. Each activation holds the single permit while it does its work and releases it afterwards. [U]
R3. At most one activation may hold the permit at any moment.
R4. An activation that cannot obtain the permit waits until the permit becomes available.
R5. Every schedule and interleaving must terminate.
R6. All three worker roles complete.
R7. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2, w3.
- Shared resources: s (semaphore).
