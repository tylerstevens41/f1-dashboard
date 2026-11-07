# Automated 2026 season preparation

## One-command operation

From the repository root on `feat/automatic-circuit-preparation`:

```powershell
git switch feat/automatic-circuit-preparation
git pull --ff-only origin feat/automatic-circuit-preparation
.\.venv\Scripts\python.exe -m bridge.season_preparation --year 2026 --login
```

This uses the existing LiveF1 environment and dedicated `.venv-fastf1` worker.
It does not install FastF1 into `.venv`, change authentication, ask for circuit
names/offsets/paths or require annotation imports. A valid existing FastF1 token
is still required; if expired, use its existing interactive authentication command
locally and rerun. Never send credentials or tokens to the assistant.

Inventory-only mode is offline and does not create directories, refresh session
metadata, write reports, download telemetry or modify circuit data:

```powershell
.\.venv\Scripts\python.exe -m bridge.season_preparation --year 2026 --dry-run
```

Resume is automatic; this equivalent spelling is available:

```powershell
.\.venv\Scripts\python.exe -m bridge.season_preparation --year 2026 --resume --login
```

Exit code 2 means the pass finished with incomplete/failed/unavailable items; it
is not a reason to delete assets. Inspect the report, fix authentication if needed,
and rerun after the listed retry time. Completed work is retained.

## Calendar scope and provenance

The user explicitly selected the **22-event preparation scope** excluding Bahrain
and Saudi Arabia after reviewing a discrepancy. The current November official F1
calendar actually lists 23 rounds, including the Bahrain-branded race at Sepang.
We do not label the 22-item selection as the latest official full calendar, add
Sepang silently or mistake the cancelled Sakhir/Jeddah races for active venues.
The versioned `bridge/data/calendar-2026.json` includes source URLs, retrieval
UTC timestamp, the explicit scope, exclusions and discrepancy. It is cached source
metadata, not a live calendar-refresh service; future amendments require reviewing
and updating that versioned snapshot. Other years have no bundled calendar and
are not silently treated as 2026.

Sources:

- https://www.formula1.com/en/racing/2026
- https://www.fia.com/news/fia-and-formula-1-announce-2026-calendar
- https://admin.fia.com/news/fia-and-fom-confirm-malaysia-will-join-2026-calendar-host-venue-bahrain-grand-prix

Calendar venue aliases do not contain LiveF1 keys, dates or archive paths. Names
are accent-normalized and matched against actual circuit/venue metadata, with
separate Barcelona/Madrid and Austin/Miami/Las Vegas entries. Country aliases
alone do not establish circuit identity.

## Inventory, persistence and source selection

The orchestrator inventories the existing dynamic store and original public
Austin registry files before source retrieval. It validates revision pointers,
geometry identity, calibration checks, annotation fingerprints and completion.
Valid dynamic circuits are skipped. Partial dynamic circuits resume using their
existing geometry/source session. Reviewed public Austin files are never rewritten
or migrated: if source season or annotations cannot be confirmed, they are
protected and reported partial. Corrupt assets are reported and blocked rather
than automatically deleted/repaired. Multiple matching assets are blocked for
review. Private caches and reports remain ignored by Git.

Each item uses the exact shared `preparation.prepare` coordinator, geometry cleaner,
reconstruction, corner registration, multi-lap sector calculation, checkpointing
and asset publication. No alternative circuit algorithms or rendering paths exist.
Race sessions older than six hours are preferred; this is only a candidate-completion
guard, not proof that topics are available. If geometry cannot be obtained, other
published Qualifying/Practice candidates can be tried sequentially, preserving
source session/reason. A usable geometry or partial annotation result stops session
substitution and retains that source. Normal bounded GPS-window discovery applies;
users do not enter offsets.

Up to two earlier season catalogs are searched when no completed target-season
candidate exists. **Older candidates are not automatically promoted to 2026.**
Venue names and stable circuit keys cannot independently prove layout/GPS-coordinate
compatibility. The report lists candidates with the reason
`older-source-found-layout-compatibility-unverified`. This is an intentional
remaining limitation of fully automatic fallback, not a claim that source and
target layouts match. New venues with no usable history remain unavailable.
No earlier-year asset is relabelled, registered or fabricated as 2026-compatible.

The queue is sequential. `season-2026/season.lock` prevents duplicate batch processes;
a stale PID lock is recovered after a crash. Each item is checkpointed before and
after work. Atomic reports and the existing atomic revision/checkpoint writes use
bounded Windows file-lock recovery. Session metadata catalogs are cached for 24
hours; GPS/source caches remain under their existing limits. There are no new
HTTP retry loops or timeout increases. Explicit retry eligibility imposes a
five-minute failed/partial cooldown or one-hour unavailable cooldown across runs;
valid assets always override stale queue status on resume. Authentication failures
are classified separately and do not repeat the same season-index request for
all 22 circuits.

## Reports and frontend availability

```powershell
$report = Get-Content .\circuit-assets\season-2026\report.json -Raw | ConvertFrom-Json
$report.humanSummary
$report.summary
$report.queue | Select-Object name,status,sourceSeason,targetSeason,reason,nextRetryAt
$report.discoveryErrors | ConvertTo-Json -Depth 8
$report.queue | ConvertTo-Json -Depth 30
```

The persistent JSON contains the scope/provenance, inventory integrity, calibration
and annotation status, checkpoint counts, queue/attempt state, selected sessions
and reasons, fallback candidates, accepted GPS/lap counts, calibration/registration
metrics, corner count, all three boundary estimates, failure category/details,
cache paths and retry times. `details.testPlayback` derives a candidate TEST window
from the successful source, with no guessed offset. All reports retain provisional
accuracy/verification status. `humanSummary` is the persistent readable summary;
console output reports per-item stages and final counts.

Assets use the existing `circuit-assets/circuit-<actual-key>-2026` layout with
immutable revision files and atomic `current.json`. Checkpoints and worker diagnostics
stay alongside each circuit. `gps-cache`, `fastf1-cache` and `annotation-sources`
are unchanged. No raw telemetry is embedded in the season report.

The existing backend resolves newly prepared assets from their published circuit
key/season when the corresponding session is selected. No React registry editing,
Vite rebuild, manual JSON import or geometry regeneration is required. After an
external CLI batch, reselect the session or refresh the dashboard to request the
new assets. Appearance, label layout, editor, animation, timing tower and LIVE/TEST
processing are unchanged. Runtime compatibility checks still gate live markers;
preparation does not prove future-session coordinate compatibility.

## Validation in this environment

The dry-run completed with 22 planned items, zero local assets and no downloads or
writes. The user's real Austin/Mexico/Suzuka files are not present here; their
recognition was validated with explicitly synthetic storage fixtures, not asserted
from a real local inventory. A real batch attempt classified archive authentication
failure for all 22 queued events after one season-index request. No geometry,
annotation, source session or full-season preparation success is claimed.

Tests cover the 22-event scope and source discrepancy, event normalization,
read-only inventory/dry run, complete skips, partial recovery, existing public
Austin plus dynamic Mexico/Suzuka preservation, source ordering and future sessions,
strict older-layout rejection, authentication classification, failure continuation,
restart/resume, cooldown and idempotence. Existing shared registry/renderer,
checkpoint, crossover, animation, importer, sector and Windows atomic-write suites
remain the regression coverage. Local authenticated execution is still required
for every missing real circuit; unavailable or unverified fallback circuits mean
full-season completion remains incomplete.
