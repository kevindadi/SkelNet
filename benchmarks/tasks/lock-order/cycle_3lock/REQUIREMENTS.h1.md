# Requirements

R1. The design contains one main thread and three worker threads.
R2. Three locks are shared among the workers, and none of them may be held by more than one worker at a time.
R3. The first worker needs the first and second lock, the second worker needs the second and third lock, and the third worker needs the third and the first lock.
R4. Each worker must hold its two locks at the same time while it performs its critical work.
R5. No worker may wait forever.
R6. Every worker must release each lock it holds before it finishes.
R7. The main thread starts all three workers and only finishes after all three have finished.
R8. Every worker must finish eventually, whatever order the workers run in.
R9. Every possible schedule or interleaving of the workers must terminate.
R10. The program must print exactly the line `DONE t1=1 t2=1 t3=1` and then exit. Each worker performs its critical work exactly once; while holding its locks it adds one to its own completion count kept in lock-protected shared state, and the program prints each worker's count.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): t1, t2, t3.
- Shared resources: a (lock), b (lock), c (lock).
