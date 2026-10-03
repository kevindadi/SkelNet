# Requirements

R1. A main task starts two sensor roles and two recorder roles that run at the same time. [U]
R2. The sensors and the recorders share one single-slot tray that can hold at most one reading, and every access to the tray is guarded by one lock.
R3. A sensor must wait while the tray is occupied, and must place its reading only when the tray is free.
R4. A recorder must wait while the tray is empty, and must pick up a reading only when one is present.
R5. A sensor must signal the recorders after it has placed a reading.
R6. A recorder must signal the sensors after it has picked up a reading.
R7. Every reading that is placed must eventually be picked up, and every schedule must terminate with all four roles finished.
R8. In every state the tray holds at most one reading.
R9. The two readings are each picked up exactly once.
R10. The program must print exactly the line `DONE total=14` and then exit. The value is the sum of the two reading values that the recorders actually picked up, not a constant written into the print. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): sensor_a, sensor_b, recorder_a, recorder_b.
- Shared resources: tray_lock (lock), tray_empty (condition variable), tray_full (condition variable).
