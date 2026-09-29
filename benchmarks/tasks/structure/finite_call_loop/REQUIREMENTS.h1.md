# Requirements

R1. A main task calls the auxiliary routine helper twice, completing the same call sequence on each iteration.
R2. The main task and the auxiliary routine share no mutexes, counters, or other shared state, so no two tasks contend for a resource.
R3. Each auxiliary call runs to completion before the calling task starts the next call.
R4. Every schedule and interleaving of the tasks must terminate.
R5. Count completed auxiliary calls from their return values. The program must print exactly the line `DONE calls=2` and then exit.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): helper.
