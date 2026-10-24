# Microsoft Fabric setup (Real-Time Intelligence)

Goal: every match event that FootieManager ingests also lands in a Fabric **Eventhouse**, where it can be queried with KQL while the match plays. That gives the "data platform" story: the same feed powers the app and an analyst's live queries.

The app works without this. It's optional and off by default.

## 1. Create the Eventstream

1. In your Fabric workspace, create an **Eventhouse** (this also creates a KQL database).
2. Create an **Eventstream**.
3. Add a **Custom endpoint** source. Open its details and copy the **Event Hub** connection string (with the entity/event hub name).
4. Add the KQL database as a destination, with a new table `MatchEvents` and JSON input.

Menu names in the Fabric UI change often. If a step doesn't match, look for "custom endpoint" (source) and "Eventhouse / KQL database" (destination).

## 2. Point FootieManager at it

```powershell
cd backend
pip install azure-eventhub
```

In `backend/.env`:

```
FABRIC_EVENTSTREAM_CONNECTION_STRING=Endpoint=sb://...;SharedAccessKeyName=...;SharedAccessKey=...;EntityPath=...
FABRIC_EVENTSTREAM_NAME=            # only if EntityPath is not in the string
```

Restart the backend. The **Fabric** badge turns green. Each viewer connection forwards events as they are ingested (see `FabricEventstreamSink` in [backend/footie/pipeline/ingest.py](../backend/footie/pipeline/ingest.py)).

## 3. Event shape

One JSON object per event (also in `data/<scenario>/events.jsonl`):

| Field | Example | Notes |
|---|---|---|
| `id` | `1910` | Unique per match |
| `match_id` | `"comeback-29"` | |
| `t` | `4118.37` | Seconds since kick-off, continuous across halves |
| `period`, `clock` | `2`, `3966.83` | Clock is the display clock in seconds (45:00 at the second-half start) |
| `type` | `"shot"` | `pass`, `carry`, `shot`, `pressure`, `tackle`, `interception`, `recovery`, `save`, `foul`, `card`, `corner`, `throw_in`, `goal_kick`, `substitution`, `period_start`, `period_end` |
| `side`, `team` | `"away"`, `"RVA"` | |
| `player` | `"RVA-11"` | |
| `x`, `y`, `end_x`, `end_y` | metres | 105 × 68 pitch, home attacks towards x = 105 |
| `duration` | seconds | Ball travel time (passes, carries, shots) |
| `outcome` | `"goal"` | Pass: `complete`/`incomplete`/`out`. Shot: `goal`/`saved`/`off_target`/`blocked`/`post` |
| `recipient`, `pass_type`, `body_part`, `card`, `player_off`, ... | | Type-specific |

## 4. Example KQL

```kusto
// Shots and goals so far, per team
MatchEvents
| where type == "shot"
| summarize shots = count(), goals = countif(outcome == "goal") by team

// Pressing intensity in 5-minute buckets
MatchEvents
| where type == "pressure"
| summarize pressures = count() by team, bucket = bin(todouble(clock) / 60, 5)
| order by bucket asc

// Longest passes completed
MatchEvents
| where type == "pass" and outcome == "complete"
| extend dist = sqrt(pow(todouble(end_x) - todouble(x), 2) + pow(todouble(end_y) - todouble(y), 2))
| top 10 by dist
```

A Real-Time Dashboard on these queries makes a good 20-second segment in the demo video.
