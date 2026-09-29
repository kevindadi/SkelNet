# Requirements

R1. The design contains two modules, where one module owns the first shared resource and the other module owns the second shared resource.
R2. One task runs in the first module and another task runs in the second module, and both tasks need both resources.
R3. Each task must declare that it depends on the resource owned by the other module.
R4. Each task must hold both resources at the same time while it performs its work.
R5. No task may hold a resource while it waits forever for another task to release a resource it needs.
R6. Every task must release each resource it holds before it finishes.
R7. A starting thread launches both tasks and only finishes after both tasks have finished.
R8. Both tasks must finish even though they run in different modules.
R9. Every possible schedule or interleaving must terminate.
R10. The program must print exactly the line `DONE t1=1 t2=1` and then exit. Each task enters its critical section exactly once and reports, under the protection of the resources, the number of completed critical sections it holds for itself.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): t1, t2.
- Shared resources: a (lock), b (lock).
