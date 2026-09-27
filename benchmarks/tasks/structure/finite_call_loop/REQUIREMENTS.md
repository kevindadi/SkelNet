# Requirements

R1. A main task calls an auxiliary routine and then begins the same call sequence again. [U]
R2. The main task and the auxiliary routine share no mutexes, counters, or other shared state, so no two tasks contend for a resource.
R3. Each auxiliary call runs to completion before the calling task starts the next call.
R4. Every schedule and interleaving of the tasks must terminate.
R5. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): helper.
