# Requirements

R1. The design contains one main thread and three worker threads.
R2. Three locks are shared among the workers, and none of them may be held by more than one worker at a time.
R3. The first worker needs the first and second lock, the second worker needs the second and third lock, and the third worker needs the third and the first lock.
R4. Each worker must hold its two locks at the same time while it performs its critical work.
R5. It must never be possible for the workers to leave one another waiting forever, each holding one lock and needing another.
R6. Every worker must release each lock it holds before it finishes.
R7. The main thread starts all three workers and only finishes after all three have finished.
R8. Every worker must finish eventually, whatever order the workers run in.
R9. Every possible schedule or interleaving of the workers must terminate.
R10. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): t1, t2, t3.
- Shared resources: a (lock), b (lock), c (lock).
