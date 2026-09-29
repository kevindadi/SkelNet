# Requirements

R1. A main task starts one outer worker.
R2. The outer worker starts a nested group of two inner tasks.
R3. Each inner task takes mutex A and mutex B, holds both at the same time, and increments each mutex-protected counter once. Both counters start at zero.
R4. Every possible schedule must terminate; no inner task may wait forever.
R5. The outer worker completes, and it only completes after both inner tasks have finished.
R6. Every schedule and interleaving of the tasks must terminate.
R7. After outer and both inner tasks finish, report the final protected counters. The program must print exactly the line `DONE a=2 b=2` and then exit.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): outer, x1, x2.
- Shared resources: a (lock), b (lock).
