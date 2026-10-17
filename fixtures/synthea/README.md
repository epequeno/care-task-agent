# Fixtures — synthetic patients only

`bundle_p1.json` is a hand-built synthetic FHIR R4 Bundle for one invented patient
(`P1`): profile, two appointments, two medication requests, two care tasks. It is a
fixture, not a claim about any real patient, and it is what the offline tests and the
offline eval run against.

## Generating more with Synthea

For a wider set, generate synthetic patients locally with
[Synthea](https://github.com/synthetichealth/synthea) — deterministic given a seed,
offline, and no PHI:

```bash
git clone https://github.com/synthetichealth/synthea
cd synthea && ./run_synthea -p 5 -s 42
# output/fhir/*.json — import a handful as fixtures
```

Keep the committed fixture small: a reviewer should be able to read it in one screen.

## Live reads

The live half reads a **public FHIR sandbox** (SMART Health IT, Epic on FHIR, or HAPI),
never a real system — see `docs/API-NOTES.md` and the seam note in `README.md`.
