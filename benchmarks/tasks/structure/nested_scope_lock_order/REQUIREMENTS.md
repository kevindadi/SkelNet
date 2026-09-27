# Requirements

R1. A main task starts one outer worker. [U]
R2. The outer worker starts a nested group of two inner tasks. [U]
R3. Each inner task takes mutex A and mutex B and, at some point, holds both of them at the same time.
R4. The two inner tasks take the mutexes in the same order so that no wait cycle can form.
R5. The outer worker completes, and it only completes after both inner tasks have finished.
R6. Every schedule and interleaving of the tasks must terminate.
R7. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): outer, x1, x2.
- Shared resources: a (lock), b (lock).
