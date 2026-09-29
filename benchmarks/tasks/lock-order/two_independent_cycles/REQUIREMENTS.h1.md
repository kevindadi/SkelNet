# Requirements

R1. The design contains one main thread and four worker threads.
R2. Four locks are shared among the workers, arranged as a first pair and a second pair.
R3. The first two workers each need both locks of the first pair, and the last two workers each need both locks of the second pair.
R4. Each worker must hold both locks of its pair at the same time while it works.
R5. The two pairs must be independent, so that progress in one pair does not depend on the other pair.
R6. Within the first pair, the two workers must not be able to leave each other waiting forever.
R7. Within the second pair, the two workers must not be able to leave each other waiting forever.
R8. No worker may hold one lock of its pair while waiting forever for the other lock of that pair.
R9. Every worker must release each lock it holds before it finishes.
R10. The main thread starts all four workers and only finishes after all four have finished.
R11. Every possible schedule or interleaving of the workers must terminate.
R12. The program must print exactly the line `DONE t1=1 t2=1 t3=1 t4=1` and then exit. Each worker enters its critical section exactly once and reports, under the protection of the locks, the number of completed critical sections it holds for itself.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): t1, t2, t3, t4.
- Shared resources: a (lock), b (lock), c (lock), d (lock).
