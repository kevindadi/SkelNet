# Requirements

R1. A main task starts a waiter role and a notifier role that run at the same time.
R2. The waiter and the notifier share one lock, one condition variable, and one boolean flag that the lock guards. [U]
R3. The notifier sets the shared flag to true while holding the lock, signals the condition variable, and then releases the lock.
R4. The waiter checks the flag while holding the lock, waits on the condition variable only while the flag is false, and re-checks the flag after every wake.
R5. The waiter must complete even when the notifier's signal happens before the waiter starts waiting.
R6. The flag must be set to true before the signal is issued, so a waiting role never misses the notification.
R7. The flag is read and written only while the lock is held, and the waiter releases the lock while blocked.
R8. Every schedule and interleaving must terminate with the waiter and the notifier both finished.
R9. The shared flag becomes true in every schedule.
R10. The program must print exactly the line `DONE ready=true` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): waiter, notifier.
- Shared resources: m (lock), cv (condition variable), ready (shared variable).
