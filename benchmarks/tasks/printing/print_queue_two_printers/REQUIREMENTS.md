# Requirements

R1. A main task starts a spooler role and two printer roles that run at the same time. [U]
R2. The spooler and the two printers share one print queue that can hold at most one job.
R3. The spooler puts four print jobs into the queue, one at a time.
R4. The printers take jobs from the queue, and a printer must wait when the queue is empty.
R5. After the spooler has put all four jobs into the queue it must signal shutdown so that every printer can stop.
R6. Each printer must take two jobs and then exit once shutdown is signalled.
R7. Every schedule and interleaving must terminate with the spooler and both printers finished.
R8. In every state the shared printed counter is at most three.
R9. The program must print exactly the line `DONE pages=10` and then exit. The value is the sum of the four job sizes the printers actually took, not a constant written into the print. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): spooler, printer1, printer2.
- Shared resources: ledger (lock), queue (channel), halt (semaphore).
