Create a modest day-by-day itinerary from the supplied guide evidence.
Return {"activities":[{"date":"YYYY-MM-DD","claim":"one factual recommendation",
"evidence_id":"source ID","quote":"exact supporting substring","exposure":"indoor|outdoor|unknown"}]}.
Cover every accepted inclusive date when distinct relevant evidence supports doing so. At most two
activities per day, 28 total. Split independent recommendations into separate entries. Reusing a
source is allowed only for distinct facts it actually supports. Never duplicate an activity to fill days.
Leave uncovered dates empty instead of inventing facts. Identify exposure only when the passage
supports it. No current hours, tickets, travel durations, accessibility or safety guarantees.
Respect supplied flight arrival/departure constraints and hotel location; mark travel days through
omission when the application reserves them. All recommendations remain planning suggestions.
