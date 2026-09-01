# Deploy — Kundendeployment mit Rückweg

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md)

---

## Deutsch

`sccs deploy` verschickt eine **benannte, szenario-scoped Teilmenge** des lokalen Claude-Code-Inventars — Skills, Agents, Commands, Framework-Dateien, Shell-Config — an einen **fremden Host**, typischerweise einen Kundenserver mit Odoo. Später nimmt derselbe Befehl die Lieferung wieder ab und **prüft**, dass wirklich nichts zurückgeblieben ist.

### Unterschied zu Export/Import

[docs/usage/transfer.md](transfer.md) (`sccs export`/`sccs import`) ist das allgemeine Werkzeug: ein Ad-hoc-ZIP aus frei gewählten Items, ohne Gedächtnis, ohne Rückweg. Ideal, um einmalig etwas herüberzureichen.

`sccs deploy` ist enger und dafür repeatbar:

| | `sccs export`/`import` | `sccs deploy` |
|---|---|---|
| Auswahl | frei, pro Lauf | ein benanntes **Profil** |
| Zielplattform | die des exportierenden Rechners | die des **Profils** |
| Ziel-Config nötig? | nein (ZIP ist Rohdaten) | nein — das Bundle trägt seine eigene Removal-Policy |
| Rückweg | keiner | `sccs deploy revoke` mit Verifikations-Sweep |
| Zweck | einmaliger Transfer | wiederholbarer Einsatz + saubere Abnahme |

Kurz: `export`/`import` ist irgendein ZIP von irgendwas. `deploy` ist ein wiederholbares Profil **mit einem Weg zurück**.

### Subcommands

```bash
sccs deploy list                                # Profile anzeigen
sccs deploy show odoo-server                     # Profil gegen den lokalen Baum auflösen
sccs deploy show odoo-server --platform linux    # gegen eine andere Zielplattform prüfen
sccs deploy export odoo-server -o kunde.zip       # Bundle bauen
sccs deploy install kunde.zip                     # auf dem Zielrechner installieren
sccs deploy status                                # was hier per Deploy installiert ist
sccs deploy revoke                                # wieder abnehmen + verifizieren
```

### Die vier mitgelieferten Profile

| Profil | Zweck | Umfang |
|---|---|---|
| `odoo-server` | Odoo-Arbeit auf einem Kundenserver | 17 Skills, 4 Commands, 2 Agents, die 4 Framework-Dateien, Fish-Config + Functions, Starship. Auf dem Rechner des Maintainers lösen sich daraus 122 Items auf. |
| `odoo-dev-full` | wie `odoo-server`, plus Dokumentations- und Publikations-Skills | erweitert `odoo-server` |
| `fastreport` | FastReport-Arbeit auf einem Kundenserver | eigene Skill-/Agent-Auswahl |
| `shell-only` | reine Umgebung, kein Wissen | jede Kategorie steht auf `retain` — `revoke` entfernt nichts |

Eigene Profile überschreiben mitgelieferte per Name in `deployment_profiles:` in der `config.yaml`; die bundle-seitigen Defaults stehen in `sccs/deploy/defaults.py`.

### `sccs deploy show` — Auflösung gegen den lokalen Baum

```
Profile: odoo-server (platform: linux)
  Items resolved: 122
  Missing:        0
  Unmet skill dependencies: 0
```

Zeigt, welche Items das Profil tatsächlich trifft, was auf der lokalen Maschine fehlt, und welche Skill-Abhängigkeiten (`INHERITS FROM:`-Zeile in `SKILL.md`) unerfüllt bleiben. `--platform` prüft gegen eine andere Zielplattform als die lokale.

### `sccs deploy export` — das Bundle bauen

```bash
sccs deploy export odoo-server -o kunde.zip
sccs deploy export odoo-server -o kunde.zip --platform linux    # Zielplattform explizit
sccs deploy export odoo-server -n                                # Dry-Run, nichts geschrieben
sccs deploy export odoo-server -o kunde.zip --allow-missing-deps # trotz unerfüllter Skill-Deps bauen
```

Drei Regeln, die sonst falsch verstanden werden:

1. **Die Zielplattform ist die des Profils, nicht die des exportierenden Rechners.** Ein Mac würde sonst macOS-only-Fish-Dateien in ein Linux-Bundle packen.
2. **Das Bundle ist selbstbeschreibend.** Der Kundenhost hat kein `config.yaml` von uns — also trägt das Manifest selbst Profil, Zielplattform, `retain`-Liste und die Sweep-Globs für `revoke`. `deploy install` funktioniert deshalb **ohne jede SCCS-Konfiguration** auf dem Zielrechner; das ist der Normalfall, kein Fehlerpfad.
3. **`retain` gehört zum Profil, nicht zur Kategorie.** Dieselbe Fish-Config ist Nutzlast auf einer zweiten eigenen Maschine — und Abschiedsgeschenk auf einem Kundenhost. `shell-only` behält deshalb alles (`retain` auf jeder Kategorie), während `odoo-server` die Shell-Config zwar mitliefert, sie beim `revoke` aber stehen lässt und nur das Wissen — Skills, Agents, Commands, Framework-Dateien — wieder abzieht.

Ein wissenstragendes Bundle bekommt außerdem einen generierten `/sccs-cleanup`-Command mit — damit der Agent auf dem Kundenhost eine definierte Route hat, statt sich mit `rm -rf` zu improvisieren.

### `sccs deploy install` — auf dem Zielrechner

```bash
sccs deploy install kunde.zip -n     # Vorschau
sccs deploy install kunde.zip        # schreibt + hinterlegt eine Quittung
```

Schreibt die Dateien und legt eine **Quittung** (Receipt, Schema-Version 2) an, die spätere `status`- und `revoke`-Läufe lesen. **Ownership entscheidet über Löschung**, und das prägt auch das Schreiben selbst:

- Ein Ziel, das **vor** der Installation bereits existierte, wird als `pre_existing` vermerkt und beim Install **übersprungen** — es wird nicht überschrieben, sondern gemeldet. Vor dieser Version wurde ein solches Ziel noch überschrieben; das war der Fehler.
- Ein Ziel, das SCCS selbst geschrieben hat, wird normal aktualisiert.

Ein Receipt einer älteren SCCS-Version (Schema < 2) wird mit einer konkreten Fehlermeldung zurückgewiesen, statt unter neuen Annahmen gelesen zu werden.

### `sccs deploy status` — was steht auf diesem Host

Liest die Quittung und zeigt, was hier per Deploy installiert wurde, mit welchem Profil und welcher Zielplattform.

### `sccs deploy revoke` — abnehmen und verifizieren

```bash
sccs deploy revoke -n              # Vorschau
sccs deploy revoke                 # fragt nach Bestätigung, entfernt dann
sccs deploy revoke -y              # ohne Nachfrage
sccs deploy revoke --keep-traces   # Transkripte/Config-Spuren NICHT entfernen
sccs deploy revoke --profile fastreport   # falls mehrere Profile auf dem Host koexistieren
```

**Ownership entscheidet, was verschwindet:**

- Ein als `pre_existing` vermerktes Ziel wird **nie** entfernt.
- Ein von SCCS installiertes Ziel, das der Kunde zwischenzeitlich bearbeitet hat, **wird** entfernt — und als verändert geflaggt. Das sind zwei verschiedene Tatsachen über „die Datei hat sich geändert“, nicht zwei Abstufungen derselben.
- Ein Artefakt, das ein **anderes, noch installiertes** Profil ebenfalls beansprucht, geht in den `shared`-Topf und bleibt liegen — `odoo-server` und `fastreport` liefern beide `odoo-common` aus.

**Was über die reinen Profil-Items hinaus mitgeht:**

- Das **Transkript ist das Leck, nicht der Skill**: `~/.claude/projects/` zitiert Skill-Inhalte wortwörtlich in die Session-History — inklusive Pläne, Todos und Shell-Snapshots. Das geht mit.
- `~/.claude.json` wird **nicht gelöscht**, sondern nur um den Schlüssel `history` **getrimmt** — die Datei trägt auch Auth- und Onboarding-Zustand des Host-Nutzers.
- Ein symlinktes Ziel wird auf sein aufgelöstes Ziel reduziert; ein Ziel, das außerhalb von `$HOME` aufgelöst, wird **verweigert**, statt stillschweigend Erfolg zu melden.
- `~/.config/sccs/` wird zur Laufzeit durchsucht und mitentfernt — allein `.sync_state.yaml` nennt jeden synchronisierten Skill. **Ausnahme**: existierte dieses Verzeichnis schon vor der Installation, betreibt der Host-Nutzer SCCS selbst — dann bleibt es unangetastet, und `revoke` sagt das im Bericht. Die Quittung selbst ist von der Entfernung ausgenommen und wird zuletzt gelöscht.

**Die Verifikations-Sweep am Ende** re-scannt die ausgelieferten Namen unabhängig von der Quittungs-Buchhaltung. Drei Ausgänge:

1. Ein zur Entfernung vorgesehener Name, der noch da ist → **Fehler** (Exit ≠ 0).
2. Ein Name ohne jeden Quittungseintrag → ebenfalls **Fehler**.
3. Ein Name, der beweislich nie von SCCS geschrieben wurde → wird gemeldet und gekennzeichnet, ist aber **kein** Fehler — außer sein Inhalt ist byte-identisch mit dem, was das Bundle geliefert hätte; dann liegt unser Wissen trotzdem auf dem Host, und es zählt wieder als Fehler.

### Bestätigung und Sicherheit

Entfernen verlangt eine Bestätigung. `--json` impliziert non-interaktiv und verweigert ohne `-y/--yes`, statt eine Nachfrage in den eigenen Ausgabestrom zu drucken.

### Blockierte Kategorien

`claude_memories`, `claude_plans` und `claude_todos` dürfen **nie** in einem Deployment-Profil auftauchen — der Schema-Validator wirft, sobald eine davon versucht wird aufzunehmen. Das ist Projektgedächtnis aus anderen Engagements und hat auf einem Kundenhost nichts zu suchen.

### Ablauf im Überblick

```bash
# lokal
sccs deploy show odoo-server --platform linux
sccs deploy export odoo-server -o odoo-server.zip --platform linux
scp odoo-server.zip kunde-host:~/

# auf dem Kundenhost
sccs deploy install odoo-server.zip
sccs deploy status

# ... Arbeit auf dem Kundenhost ...

# Abnahme
sccs deploy revoke -y
```

Querverweise: [transfer.md](transfer.md), [profiles.md](profiles.md), [categories.md](categories.md), [cli-reference.md](cli-reference.md)

---

## English

`sccs deploy` ships a **named, scenario-scoped slice** of the local Claude Code inventory — skills, agents, commands, framework files, shell config — to a **foreign host**, typically a customer's Odoo server. The same command family later takes the delivery back off and **verifies** that nothing was left behind.

### How this differs from Export/Import

[docs/usage/transfer.md](transfer.md) (`sccs export`/`sccs import`) is the general-purpose tool: an ad-hoc ZIP of whatever items you pick, with no memory and no way back. Good for handing something over once.

`sccs deploy` is narrower and repeatable instead:

| | `sccs export`/`import` | `sccs deploy` |
|---|---|---|
| Selection | free, per run | one named **profile** |
| Target platform | the exporting machine's | the **profile's** |
| Target config required? | no (a ZIP is raw data) | no — the bundle carries its own removal policy |
| Way back | none | `sccs deploy revoke` with a verification sweep |
| Purpose | one-off transfer | repeatable deployment + a clean handback |

In short: `export`/`import` is any ZIP of anything. `deploy` is a repeatable profile **with a way back**.

### Subcommands

```bash
sccs deploy list                                # show the deployment profiles
sccs deploy show odoo-server                     # resolve a profile against the local tree
sccs deploy show odoo-server --platform linux    # check against a different target platform
sccs deploy export odoo-server -o customer.zip    # build the bundle
sccs deploy install customer.zip                  # install on the target host
sccs deploy status                                # what deploy installed on this host
sccs deploy revoke                                # take it back off and verify
```

### The four bundled profiles

| Profile | Purpose | Scope |
|---|---|---|
| `odoo-server` | Odoo work on a customer server | 17 skills, 4 commands, 2 agents, the 4 framework files, fish config + functions, starship. 122 items resolved on the maintainer's machine. |
| `odoo-dev-full` | `odoo-server`, plus documentation and publication skills | extends `odoo-server` |
| `fastreport` | FastReport work on a customer server | its own skill/agent selection |
| `shell-only` | environment only, no knowledge | every category is retained — `revoke` removes nothing |

Custom profiles override the bundled ones by name via `deployment_profiles:` in `config.yaml`; the bundled defaults live in `sccs/deploy/defaults.py`.

### `sccs deploy show` — resolving against the local tree

```
Profile: odoo-server (platform: linux)
  Items resolved: 122
  Missing:        0
  Unmet skill dependencies: 0
```

Shows which items the profile actually resolves to, what is missing locally, and which skill dependencies (the `INHERITS FROM:` line in `SKILL.md`) go unmet. `--platform` checks against a target platform other than the local one.

### `sccs deploy export` — building the bundle

```bash
sccs deploy export odoo-server -o customer.zip
sccs deploy export odoo-server -o customer.zip --platform linux   # explicit target platform
sccs deploy export odoo-server -n                                 # dry-run, nothing written
sccs deploy export odoo-server -o customer.zip --allow-missing-deps  # build despite unmet skill deps
```

Three rules a reader would otherwise get wrong:

1. **The target platform is the profile's, not the exporting machine's.** Otherwise a Mac would pack macOS-only fish files into a bundle meant for Linux.
2. **The bundle is self-describing.** The customer host has no `config.yaml` of ours, so the manifest itself carries the profile, target platform, `retain` list and the sweep globs `revoke` needs later. `deploy install` therefore works with **no SCCS configuration at all** on the target — that is the normal case, not an error path.
3. **`retain` belongs to the profile, not the category.** The same fish config is payload on a second machine of ours — and a parting gift on a customer host. `shell-only` keeps everything (every category set to `retain`), while `odoo-server` ships the shell config too but leaves it behind on `revoke`, pulling back only the knowledge — skills, agents, commands, framework files.

A knowledge-bearing bundle also gets a generated `/sccs-cleanup` command shipped alongside it, so the agent on the customer host has a defined route instead of improvising with `rm -rf`.

### `sccs deploy install` — on the target host

```bash
sccs deploy install customer.zip -n     # preview
sccs deploy install customer.zip        # writes, and records a receipt
```

Writes the files and records a **receipt** (schema version 2) that later `status` and `revoke` runs read. **Ownership decides deletion**, and that shapes the write itself:

- A target that already existed **before** the install is recorded `pre_existing` and is **skipped** during install — it is not overwritten, only reported. Before this version such a target was still overwritten; that was the bug.
- A target SCCS itself wrote is updated normally.

A receipt from an older SCCS (schema < 2) is refused with actionable text rather than read under the new assumptions.

### `sccs deploy status` — what is on this host

Reads the receipt and reports what deploy installed here, with which profile and target platform.

### `sccs deploy revoke` — taking it back off, and verifying

```bash
sccs deploy revoke -n              # preview
sccs deploy revoke                 # asks for confirmation, then removes
sccs deploy revoke -y              # skip the confirmation
sccs deploy revoke --keep-traces   # do NOT remove transcript/config traces
sccs deploy revoke --profile fastreport   # when several profiles coexist on the host
```

**Ownership decides what disappears:**

- A target recorded `pre_existing` is **never** removed.
- A target SCCS installed that the customer has since edited **is** removed — and flagged as modified. Those are two different facts about "the file changed," not two degrees of the same one.
- An artefact another **still-installed** profile also claims goes into the `shared` bucket and stays — `odoo-server` and `fastreport` both ship `odoo-common`.

**What goes beyond the plain profile items:**

- **The transcript is the leak, not the skill**: `~/.claude/projects/` quotes skill content verbatim into session history — plans, todos and shell snapshots included. That goes too.
- `~/.claude.json` is **never deleted**, only **trimmed** of the `history` key — the file also carries the host user's auth and onboarding state.
- A symlinked target is resolved down to its target; a target that resolves outside `$HOME` is **refused** rather than silently reported as a success.
- `~/.config/sccs/` is enumerated at runtime and removed too — `.sync_state.yaml` alone names every synchronised skill. **Exception**: if that directory existed before the install, the host user runs SCCS themselves — then it is left alone, and `revoke` says so in its report. The receipt itself is excluded from removal and deleted last.

**The closing verification sweep** re-scans the shipped names independently of the receipt's own bookkeeping. Three outcomes:

1. A name planned for removal that survived → a **failure** (non-zero exit).
2. A name with no receipt entry at all → also a **failure**.
3. A name proven never written by SCCS → reported and labelled, but **not** a failure — unless its content is byte-identical to what the bundle would have shipped, in which case our knowledge is on that host regardless, and it counts as a failure again.

### Confirmation and safety

Removal requires confirmation. `--json` implies non-interactive and refuses without `-y/--yes` rather than prompting into its own output stream.

### Blocked categories

`claude_memories`, `claude_plans` and `claude_todos` may **never** appear in a deployment profile — the schema validator raises the moment one is attempted. That is project memory from other engagements and has no place on a customer host.

### End-to-end flow

```bash
# locally
sccs deploy show odoo-server --platform linux
sccs deploy export odoo-server -o odoo-server.zip --platform linux
scp odoo-server.zip customer-host:~/

# on the customer host
sccs deploy install odoo-server.zip
sccs deploy status

# ... work on the customer host ...

# handback
sccs deploy revoke -y
```

See also: [transfer.md](transfer.md), [profiles.md](profiles.md), [categories.md](categories.md), [cli-reference.md](cli-reference.md)
