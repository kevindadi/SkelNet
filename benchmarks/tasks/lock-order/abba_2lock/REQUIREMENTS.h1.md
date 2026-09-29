# Requirements

R1. The design contains one main thread and two worker threads.
R2. Both worker threads share the same two locks, and neither lock may be held by more than one worker at a time.
R3. Each worker must hold both locks at the same time while it performs its critical work.
R4. A worker that finds a lock busy must wait for it to become free and then continue.
R5. No worker may hold a lock while it waits forever for another worker to release a lock it needs.
R6. The main thread starts both workers and only finishes after both workers have finished.
R7. Every worker must release each lock it holds before it finishes.
R8. Every possible schedule or interleaving of the workers must terminate.
R9. The program must print exactly the line `DONE t1=1 t2=1` and then exit. Each worker enters its critical section exactly once and reports, under the protection of the locks, the number of completed critical sections it holds for itself.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): t1, t2.
- Shared resources: a (lock), b (lock).
