# Spec

Three accounts each hold one unit and are each protected by their own lock.
Three transfer roles run at the same time: the first moves one unit from the
first account to the second, the second moves one unit from the second account
to the third, and the third moves one unit from the third account back to the
first. Each role must hold the source and destination locks at the same time
while it moves its unit, and no account may be touched without its lock. The
total number of units across the three accounts must stay at three, no account
may go negative, and every schedule must terminate with all three roles
finished. The program prints the sum of the three final balances.
