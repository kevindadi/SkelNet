# Requirements

R1. A main task starts a waiter role and a notifier role that run at the same time.
R2. The waiter and the notifier share one lock and one condition variable, and the lock guards a boolean flag. [U]
R3. The notifier sets the shared flag to true while holding the lock, signals the condition variable, and then releases the lock.
R4. While holding the lock, the waiter checks the flag first, waits on the condition variable only while the flag is false, and re-checks the flag after each wake.
R5. The waiter must complete even when the notifier signals before the waiter starts waiting.
R6. The waiter must not wait on the condition variable while the flag is already true, and must not keep the lock while blocked.
R7. Every schedule and interleaving of the two roles must terminate with both roles finished.
R8. The shared flag becomes true in every schedule.
R9. The waiter must not pass its wait until the flag is true.
R10. The program must print exactly the line `DONE ready=true` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): waiter, notifier.
- Shared resources: m (lock), cv (condition variable), ready (shared variable).
