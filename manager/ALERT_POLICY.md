# Alert Policy

## Reliable update model
This system should prefer event-driven alerts over time-based chatter.

## Send Sai a message when
1. a job scores >= 85
2. Sai replies YES and a tailored package is ready
3. the daily appliable target is reached
4. the pipeline errors or a scheduled run fails
5. an end-of-day summary is ready

## Do not spam
- do not send progress chatter for every internal step
- do not send low-value updates for weak matches
- do not send repeated alerts for the same jobId

## Strong-match alert contents
- job title
- company
- location
- salary if available
- score
- top matched skills
- key gaps
- apply link
- short reason summary
- YES/NO prompt for tailoring

## End-of-day summary contents
- number of jobs reviewed
- number of appliable jobs found
- number of strong matches
- number of tailored packages created
- biggest blockers seen that day
