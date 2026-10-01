# Requirements

R1. A main task starts a producer role and two worker roles that run at the same time.
R2. The producer and the two workers share one work channel that can hold at most one task.
R3. The producer puts four tasks into the work channel, one at a time.
R4. The workers take tasks from the work channel, and a worker must wait when the channel is empty.
R5. After the producer has put all four tasks into the channel it must signal shutdown so that every worker can stop.
R6. Each worker must take two tasks and then exit once shutdown is signalled.
R7. Every schedule and interleaving must terminate with the producer and both workers finished.
R8. In every state the shared finished counter is at most three.
R9. The program must print exactly the line `DONE sum=10` and then exit. The value is the sum of the four task values the workers actually took, not a constant written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): producer, w1, w2.
- Shared resources: m (lock), jobs (channel), stop (semaphore).
