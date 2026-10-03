# Spec

Five philosopher roles share five forks, one fork between each neighbouring
pair. A philosopher must hold both of the forks beside it at the same time in
order to eat, and it must return both forks before it finishes. To rule out a
circular wait, every philosopher takes its two forks in the same global order,
even the philosopher that owns the last and first fork. Every schedule must
terminate with all five philosophers finished, and the program must print the
sum of the ids the five philosophers return.
