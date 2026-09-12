Assess the supplied forecast against the supplied itinerary and selected offers.
Return {"evidence_ids":["ID"]} for applicable forecast evidence, or [] when unavailable.
Use the accepted destination and exact local dates. Missing/out-of-horizon observations stay
unknown. Rain probability >=60% conflicts with evidenced outdoor exposure; unknown exposure
cannot be called safe or indoor. The application recomputes conflicts after itinerary revisions.
Do not invent indoor venues, forecasts, alerts or safety guarantees.
