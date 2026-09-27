# Requirements

R1. The design contains one main thread and two short-lived workers.
R2. An independent bystander task also runs and keeps making progress without ever finishing on its own. [U]
R3. The two workers share the same two locks and also use two counting permits to coordinate with each other.
R4. Each worker must hold both locks at the same time while it enters its critical section.
R5. The two workers must use the two permits as a handshake, so that neither takes its second lock before the other has taken its first.
R6. The bystander task must not prevent the two workers from finishing.
R7. At every point during execution, it must still be possible for the first worker to finish.
R8. At every point during execution, it must still be possible for the second worker to finish.
R9. Neither worker may wait forever for a permit or a lock that the other worker never provides.
R10. Every worker must release each lock it holds before it finishes.
R11. The main thread starts all three tasks and only finishes after both workers have finished, even though the bystander may keep running.
R12. The program must print exactly the line `DONE a=1 b=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): a, b, bystander.
- Shared resources: a (lock), b (lock), sa (semaphore), sb (semaphore), flag (shared variable).
