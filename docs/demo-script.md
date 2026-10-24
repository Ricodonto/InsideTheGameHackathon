# Demo video script (about 3 minutes)

Run the app with split screen on. Have these deep links ready in tabs (dev server URLs; use port 8000 for the built app):

- A: `http://localhost:5173/?scenario=comeback&t=380&speed=5` (just before the opening goal)
- B: `http://localhost:5173/?scenario=comeback&t=4100&speed=3` (just before the 67' winner)
- C: `http://localhost:5173/?scenario=red_card&t=3530&speed=3` (red card)

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:20 | App open, both viewers, match playing at 10× | "Football is more than a scoreline. FootieManager turns a live match feed into intelligence that explains itself, and shows every fan the match their way." |
| 0:20–0:45 | Point at the five stage chips, then the pitch | "Every match is synthetic: our own engine generates events and player tracking. One pipeline in five stages: ingest, interpret, explain, render, personalise." |
| 0:45–1:25 | Tab A: opening goal lands in both viewers | "Same goal, two viewers. Left is an analyst: xG, shot speed, the move that built it. Right is a casual Riverside fan in Spanish. Both get the *why*: this goal started with a ball win high up the pitch 17 seconds earlier, and moved the win probability from 52% to 77%." |
| 1:25–1:50 | Story indices, an index alert, win-probability chart | "We track three story indices: control versus chaos, pressure and rhythm. When the game turns chaotic, viewers are told, along with the numbers behind it." |
| 1:50–2:15 | Switch Viewer B to Player focus, pick P. Dembe; tags appear on the pitch | "Player focus follows one player all match: sprints, distance, passes, milestones, tagged on the pitch when they happen." |
| 2:15–2:35 | Tab B: the 67' winner, then press Replay | "Every key moment can be replayed, with the explanation alongside." |
| 2:35–2:50 | Type in Ask the match: "Why did Northbridge lose control?" | "Fans can ask the match anything. Answers come from the live data through Microsoft Foundry and cite the moments they use." |
| 2:50–3:00 | Full-time recap card | "Automatic recaps, in any language, ready for studio, broadcast or streaming. FootieManager: inside the game." |

Tips

- Record at 1600 × 900 or larger so the overlay text is readable.
- If Foundry is on, wait a second after a goal for the **AI** badge to appear before moving on.
- If Fabric is on, cut to a KQL query in Fabric for 15 seconds after the indices segment.
