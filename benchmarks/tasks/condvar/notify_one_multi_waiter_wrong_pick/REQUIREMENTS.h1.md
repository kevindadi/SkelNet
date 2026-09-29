# Requirements

R1. A main task starts two waiter roles and one notifier role that run at the same time.
R2. Each waiter blocks on a shared condition variable until it is told to proceed.
R3. No waiter may be left waiting forever.
R4. A waiter must hold the lock while it waits on the condition variable.
R5. The notifier must take the lock before it wakes the waiters and release the lock afterwards.
R6. The waiters and the notifier use a separate permit counter so that the notifier only wakes the waiters after both are ready to wait.
R7. After the notifier has published the wake, every waiter that blocked must be able to leave the wait.
R8. Every schedule and interleaving must terminate with every waiter and the notifier finished.
R9. Every waiter completes in every schedule.
R10. The program must print exactly the line `DONE waiters=0` and then exit. The number after `waiters=` is the count of waiters still inside the wait, read from the lock after both waiters and the notifier have finished, not a constant written into the program.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): w1, w2, notifier.
- Shared resources: m (lock), cv (condition variable), g12 (semaphore), gN (semaphore).
