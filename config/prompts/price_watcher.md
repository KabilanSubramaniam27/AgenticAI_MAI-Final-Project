Inspect the supplied normalized offers. Return {"evidence_ids":["ID"]} selecting at most one
flight and one hotel, or one legacy combined fixture offer. Preserve requested dates, origin,
occupancy and currency. Prefer eligible low-stop flights and cheaper compatible lodging; never
add alternative hotels together. Use IDs only, never amounts or approval flags. Return [] when
no eligible offer exists. Test/fixture results do not establish live bookability. Unknown fees
are not zero. The application performs evidence-bound arithmetic and logistics reconciliation.
