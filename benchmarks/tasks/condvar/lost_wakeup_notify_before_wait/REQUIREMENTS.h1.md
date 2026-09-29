# Requirements

R1. A main task starts a waiter role and a notifier role that run at the same time.
R2. The waiter and the notifier share one lock, one condition variable, and one boolean flag that the lock guards.
R3. The notifier sets the shared flag to true while holding the lock, signals the condition variable, and then releases the lock.
R4. The waiter must finish whenever the flag is or becomes true, including when that happens before the waiter blocks.
R5. The waiter must complete even when the notifier's signal happens before the waiter starts waiting.
R6. A signal must not be missed when the notifier runs before the waiter blocks; the waiter must still observe the flag and finish.
R7. The flag is read and written only while the lock is held, and the waiter releases the lock while blocked.
R8. Every schedule and interleaving must terminate with the waiter and the notifier both finished.
R9. The shared flag becomes true in every schedule.
R10. The program must print exactly the line `DONE ready=true` and then exit. The text after `ready=` is the shared flag read by the waiter after it has observed that flag, not a constant written into the program.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): waiter, notifier.
- Shared resources: m (lock), cv (condition variable), ready (shared variable).
