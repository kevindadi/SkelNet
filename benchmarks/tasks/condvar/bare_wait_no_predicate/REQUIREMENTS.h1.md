# Requirements

R1. A main task starts a waiter role and a notifier role that run at the same time.
R2. The waiter and the notifier share one lock and one condition variable, and the lock guards a boolean flag.
R3. The notifier sets the shared flag to true while holding the lock, signals the condition variable, and then releases the lock.
R4. The waiter must finish whenever the flag is or becomes true, including when that happens before the waiter blocks.
R5. The waiter must complete even when the notifier signals before the waiter starts waiting.
R6. Once the flag is true the waiter must not stay blocked, and it must not keep the lock while it is blocked.
R7. Every schedule and interleaving of the two roles must terminate with both roles finished.
R8. The shared flag becomes true in every schedule.
R9. The waiter must not pass its wait until the flag is true.
R10. The program must print exactly the line `DONE ready=true` and then exit. The text after `ready=` is the shared flag read by the waiter after it has observed that flag, not a constant written into the program.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): waiter, notifier.
- Shared resources: m (lock), cv (condition variable), ready (shared variable).
