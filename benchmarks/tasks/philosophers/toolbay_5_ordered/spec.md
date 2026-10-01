# Spec

Five robot roles share five tool bays, one bay between each neighbouring pair.
A robot must occupy both of the bays it needs at the same time in order to work,
and it must release both bays before it finishes. To rule out a circular wait,
every robot claims its two bays in the same global order, even the robot that
owns the last and first bay. Every schedule must terminate with all five robots
finished, and the program must print the sum of the ids the five robots return.
