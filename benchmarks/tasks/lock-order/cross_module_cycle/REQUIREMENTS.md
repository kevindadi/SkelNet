# Requirements

R1. The design contains two modules, where one module owns the first shared resource and the other module owns the second shared resource.
R2. One task runs in the first module and another task runs in the second module, and both tasks need both resources.
R3. Each task must declare that it depends on the resource owned by the other module.
R4. Each task must hold both resources at the same time while it performs its work.
R5. It must never be possible for the two tasks to leave each other waiting forever, each holding one resource and needing the other.
R6. Every task must release each resource it holds before it finishes.
R7. A starting thread launches both tasks and only finishes after both tasks have finished.
R8. Both tasks must finish even though they run in different modules.
R9. Every possible schedule or interleaving must terminate.
R10. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): t1, t2.
- Shared resources: a (lock), b (lock).
