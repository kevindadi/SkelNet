# Spec

Four philosopher roles share four forks laid out in a ring, one fork between
each neighbouring pair. A philosopher must hold both of the forks beside it at
the same time in order to eat, and it must return both forks before it
finishes. Because each philosopher takes its left fork and then its right fork,
the fork order is cyclic; a separate waiter admits at most three philosophers
to the table at once so that at least one can always make progress. Every
schedule must terminate with all four philosophers finished, and the program
must print the sum of the ids the four philosophers return.
