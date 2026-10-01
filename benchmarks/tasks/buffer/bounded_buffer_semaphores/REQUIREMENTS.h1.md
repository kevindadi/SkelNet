# Requirements

R1. A main task starts two producer roles and two consumer roles that run at the same time.
R2. The producers and the consumers share one bounded buffer that can hold at most one item, and every access to the buffer is guarded by one mutex.
R3. A producer must take a free-slot permit before it puts its item, and must put its item only when there is room.
R4. A consumer must take an available-item permit before it takes an item, and must take an item only when one is present.
R5. A producer must signal that an item is available after it has put an item, and must not hold the mutex while it signals.
R6. A consumer must signal that a slot is free after it has taken an item, and must not hold the mutex while it signals.
R7. Every item that is put must eventually be taken, and every schedule must terminate with all four roles finished.
R8. In every state the buffer holds at most one item.
R9. The two items are each taken exactly once.
R10. The program must print exactly the line `DONE sum=11` and then exit. The value is the sum of the two item values that the consumers actually took, not a constant written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): p1, p2, c1, c2.
- Shared resources: m (lock), slots (semaphore, starts with one permit), items (semaphore, starts with no permits).
