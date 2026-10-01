# Spec

Two sensor roles and two recorder roles hand off readings through a single-slot
tray that holds at most one reading. Each sensor places exactly one reading and
each recorder picks up exactly one reading. A sensor must block while the tray is
already occupied and a recorder must block while the tray is empty; each side
must signal the other after it changes the tray. The program must terminate
under every schedule and print the sum of the two reading values that the
recorders actually picked up.
