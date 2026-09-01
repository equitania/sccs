# SCCS Deployment Profiles — scenario-scoped bundles for foreign hosts
#
# `sccs export` offers the whole synchronised inventory. On a customer
# server we want a named, reproducible slice of it — and a way to take it
# back off the machine afterwards.
#
# Design rules:
#   1. NO SECOND COPY PATH. A profile resolves to ExportSelection objects
#      and is handed to sccs.transfer.exporter.Exporter; installation goes
#      through sccs.transfer.importer.Importer.
#   2. The bundle is SELF-DESCRIBING. The customer host has no config.yaml
#      of ours, so the manifest carries the removal policy.
#   3. "written by us" and "was already here" are different facts. Only
#      the first justifies a deletion (see receipt.py:ReceiptEntry).
#   4. Project memory of other engagements (claude_memories, claude_plans,
#      claude_todos) may never enter a bundle — the validator raises.

from __future__ import annotations
