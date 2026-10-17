"""One real read against the configured FHIR server, through the real tools.

``just fhir-smoke``. No model, no MCP hop — this checks the layer below the agent:
that the scoped client reaches the server, that the search parameters the tools use
are the ones the server understands, and that what comes back is de-identified.

Point it at a server first: ``FHIR_BASE_URL=https://launch.smarthealthit.org/v/r4/fhir
just fhir-smoke``.
"""

from __future__ import annotations

import json
import sys

from care_task_agent.config import Settings
from care_task_agent.fhir.client import FhirClient
from care_task_agent.fhir.redact import find_direct_identifiers
from care_task_agent.mcp_server import tools


def main() -> int:
    settings = Settings.from_env()
    print(f"base: {settings.fhir_base_url}")

    with FhirClient(settings.fhir_base_url, settings.fhir_token) as client:
        rows = client.search("Patient", {"_count": "1"})
        if not rows:
            print("no Patient returned — nothing to read")
            return 1
        patient_id = rows[0]["id"]
        projection = tools.get_clinical_summary(client, patient_id)

    print(f"patient: {patient_id}")
    print(json.dumps(projection, indent=2))
    print(
        "reads: "
        f"{len(projection['appointments'])} appointments, "
        f"{len(projection['medications'])} medications, "
        f"{len(projection['tasks'])} tasks"
    )

    leaks = find_direct_identifiers(projection)
    print(f"direct identifiers in what the model would see: {len(leaks)}")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
