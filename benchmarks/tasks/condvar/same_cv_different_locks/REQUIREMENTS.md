# Requirements

R1. A main task starts two waiter roles and one notifier role that run at the same time. [U]
R2. Each waiter guards its own data with its own lock; the two waiters need not share one lock.
R3. Each waiter must be notified before it proceeds, and the notifier must be able to wake every waiter without depending on a race between them.
R4. A waiter must hold its own lock while it waits for the notification.
R5. Each waiter must announce that it is about to wait before it blocks, so the notifier knows how many waits to expect.
R6. The notifier must wait until both waiters have announced themselves before it wakes them.
R7. When the notifier wakes the waiters it must hold each lock that a waiter needs in order to wake and finish.
R8. The waking step must not leave any waiter blocked and must not depend on a race between the waiters.
R9. Every schedule and interleaving must terminate with all roles finished.
R10. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2, notifier.
- Shared resources: m1 (lock), m2 (lock), cv (condition variable), ready (semaphore).
