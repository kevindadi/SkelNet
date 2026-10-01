# Spec

Three pipeline stages run at the same time and are joined by two bounded
channels, each of which holds at most one value. The first stage feeds three
values into the first channel in order; the second stage drains them and
forwards one value at a time into the second channel; the third stage drains the
second channel and adds the values it receives. A single shared mutex protects a
counter that every stage bumps once. No stage may block on a channel while it
holds that mutex, so the pipeline always drains and every schedule terminates
with all three stages finished. The program must print the sum that the last
stage actually computed.
