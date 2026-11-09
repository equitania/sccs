# sccs agents — Claude Code als Supervisor, andere KI-CLIs als Prüfer

[Deutsch](#deutsch) · [English](#english)

← [Zurück zur README](../../README.md) · Warum es so gebaut ist: [Supervisor und Wrapper-Agenten](../architecture.md#supervisor-und-wrapper-agenten)

---

## Deutsch

Ein interaktives Claude-Code-Fenster arbeitet als **Supervisor**: Es gibt Reviews, zweite Meinungen und begrenzte Analysen an andere KI-CLIs ab (Codex, Antigravity/Gemini, OpenCode/Kimi) und prüft jeden zurückgekommenen Befund selbst am Code. Die Brücke sind kleine **Wrapper-Agenten** in `~/.claude/agents/`, die nur einen CLI-Aufruf weiterreichen. `sccs agents` richtet diese Wrapper ein und hält sie in Ordnung.

**`sccs agents` ist reine Konfiguration.** Es startet, verteilt oder überwacht keine Agentenarbeit, installiert keine CLIs (das macht `sccs doctor`) und meldet nirgends an (das macht jedes Werkzeug selbst).

### 1. Einrichten

```fish
sccs agents                              # Terminal: Vollbild-Ansicht
sccs agents list [--json]                # Tabelle: Agent, Werkzeug, Modell, Modus
sccs agents tools [--json]               # Installiert? Version, Login, Standardmodell, Config-Pfad
sccs agents models <tool> [--json]       # Modelle, die das Werkzeug selbst meldet
sccs agents adopt <name> [--yes]         # handgeschriebenen Wrapper übernehmen
sccs agents new <tool> <name> [--model M]    # neuen schreibgeschützten Wrapper anlegen
sccs agents set-model <name> <modell>    # Modell eines verwalteten Wrappers ändern
```

`<tool>` ist `agy` (Antigravity, immer ein Gemini-Modell), `opencode` oder `codex`. Für Pi gibt es noch keine getestete Vorlage; `sccs agents new pi …` bricht mit „Pi has no tested wrapper template yet.“ ab. Ohne Terminal (Pipe, Skript) gibt `sccs agents` die Tabelle aus statt der Vollbild-Ansicht.

**Vollbild-Ansicht.** Oben der Supervisor (Claude Code, Sitzungsmodell, Agentenordner), darunter eine Zeile je Agent mit dem Zustand seines Werkzeugs, sodass ein kaputtes Werkzeug genau an dem Agenten auftaucht, den es lahmlegt. Werkzeuge ohne Agent erscheinen als gedimmte Zeile. Die Zeile darunter erklärt den gewählten Agenten (wie Read-only erzwungen wird, ob der Export aus ist).

| Taste | Wirkung |
|---|---|
| Enter oder `m` | Modell wählen (aus der echten Modellliste des Werkzeugs) bzw. einen nicht übernommenen Wrapper übernehmen |
| `n` | neuen Wrapper anlegen |
| `w` | Werkzeug-Ansicht: Version, Login, Standardmodell, Config-Pfad, Hinweis auf `sccs doctor` |
| `?` | diese Anleitung |
| `r` | neu einlesen |
| `q` | beenden |

**Die Spalte „Mode“** zeigt `read-only` für Wrapper, die sccs verwaltet; `read-only (not adopted)` für einen handgeschriebenen Wrapper, dessen Aufrufform sccs erkennt, den es aber noch nicht übernommen hat; `unmanaged` für einen Agenten, dessen Form zu keiner Vorlage passt (sccs schreibt ihn nie); `plugin` für Agenten aus Plugins (zum Beispiel `codex:codex-rescue`, nur lesbar). Ein angehängtes `€` heißt: jeder Aufruf kostet OpenRouter-Guthaben.

**Bestehende Wrapper übernehmen.** `sccs agents adopt antigravity-worker` (oder Enter in der Ansicht) fragt einmal nach, fügt dann nur einen `sccs:`-Block in den Frontmatter ein und lässt den Rest der Datei Byte für Byte unverändert (auch CRLF und BOM bleiben). Danach funktioniert `set-model`. Mit `--yes` entfällt die Rückfrage; mit `--json` ist `--yes` Pflicht.

**Modell ändern.** `sccs agents set-model antigravity-worker gemini-4-argon-high` ändert gezielt das Modell in der Befehlszeile des Wrappers, nicht die Beschreibung und nicht den Prompt-Text. Das Modell des Wrappers selbst (`model: haiku`) bleibt fest: Der Wrapper reicht nur weiter. Das Modell wird gegen die Modellliste des Werkzeugs geprüft; lässt sich die Liste nicht lesen (offline, nicht angemeldet), wird ein formal gültiger Name mit Warnung akzeptiert und als `unverified` angezeigt. Für Antigravity muss der Name mit `gemini-` beginnen. Der Name darf nur Buchstaben, Ziffern und `. _ : / ~ -` enthalten und nicht mit `-` beginnen.

**Neuer Wrapper.** `sccs agents new opencode review-worker --model openrouter/some-model` legt `~/.claude/agents/review-worker.md` aus der mitgelieferten Vorlage an, immer schreibgeschützt. Der Name besteht aus Kleinbuchstaben, Ziffern und `-`, ohne `/` und ohne `.md`. Eine vorhandene Datei wird nie überschrieben. **Danach Claude Code neu starten**, sonst kennt die laufende Sitzung den Agenten nicht.

**Warum `Export: off`.** `~/.claude/agents` wird von sccs synchronisiert, und `sccs integrations codex|opencode|pi` exportiert Agenten in andere Werkzeuge. Ein Wrapper, der „Rufe `opencode run` auf“ sagt, hat dort nichts verloren: Er würde in OpenCode oder Codex wieder als Agent auftauchen und sich dort selbst aufrufen. Beim Anlegen und Übernehmen trägt sccs den Namen deshalb in `opencode.exclude`, `pi.exclude` und `codex.exclude` der `config.yaml` ein (einmalig, mit Backup). Stehen alle drei Einträge, zeigt die Ansicht `Export: off`. Der Wrapper selbst wird weiter zwischen Ihren Rechnern synchronisiert; auf einem Host ohne das Werkzeug zeigt die Zeile dann den fehlenden CLI-Zustand.

### 2. Arbeiten

1. Ein Terminalfenster öffnen (zum Beispiel ein Herdr-Fenster) und ins Projekt wechseln:

   ```fish
   cd ~/gitbase/mein-projekt
   claude
   ```

2. Aufgaben so stellen, wie man sie sagt:

   - „Lass den Diff von Codex, Gemini und Kimi prüfen und gleiche die Befunde am Code ab“
   - „Hol eine zweite Meinung von Gemini zu diesem Entwurf“

3. Der Supervisor startet die Wrapper **im Hintergrund**, arbeitet weiter und wird benachrichtigt, wenn ein Worker fertig ist. Er kennzeichnet jeden Befund als **ungeprüfte Behauptung** des jeweiligen Modells, prüft ihn einzeln am Code und berichtet, welche Befunde standgehalten haben und welche nicht.

Neu angelegte Agenten sieht eine bereits laufende Claude-Code-Sitzung nicht: einmal beenden und neu starten.

### 3. Läuft, fertig, hängt

- **Läuft:** Der Supervisor bekommt keine Antwort, bis der Worker fertig ist; er arbeitet in der Zwischenzeit weiter. Ein Review eines Diffs von rund 300 Zeilen dauert bei Gemini etwa vier Minuten.
- **Fertig:** Claude Code meldet das Ende des Hintergrund-Auftrags; der Supervisor liest das Ergebnis und prüft es.
- **Hängt:** Jeder Aufruf hat ein äußeres `timeout 900` (15 Minuten). Endet ein Worker mit **Exit 124**, war die Aufgabe zu groß. Dann aufteilen (ein Aufruf je Datei oder Verzeichnis, Diffs über etwa 2000 Zeilen nie am Stück) statt länger zu warten.

### 4. Fallen

- **Codex' eigene Sandbox ist nicht nono.** Ein `EPERM` auf `/tmp/xcrun_db…` in einem Codex-Lauf ist Codex' `read-only`-Sandbox bei der Arbeit. Weglassen, mit lesenden Mitteln weitermachen; keinen Neustart der nono-Sitzung verlangen.
- **Gemini braucht das Material im Prompt.** Headless kann Antigravity keine Rückfrage stellen; jeder Befehl außerhalb der Erlaubnisliste wird abgelehnt, und der Lauf endet mit `jetski: no output produced`. Der Wrapper legt deshalb den Diff oder die Auszüge in den Prompt. Taucht diese Meldung auf, fehlte Material.
- **OpenCode kostet OpenRouter-Guthaben** pro Aufruf (Markierung `€`). Ein Fehler zu Guthaben oder Anmeldung wird gemeldet, nicht mit einem anderen Anbieter wiederholt.
- **Kostenlose `opencode/*`-Modelle nicht für Kundendaten.** Die Datenrichtlinie ist unklar; der Wrapper reicht es auf Wunsch durch, sagt das aber in seiner Antwort.
- **Ein Gemini-Wrapper bleibt bei Gemini.** Antigravity verkauft auch Claude- und GPT-Modelle weiter; auf eines davon auszuweichen wäre Selbstreview. Geht kein Gemini-Modell, meldet der Wrapper das und hört auf. Dieselbe Regel steht hinter `sccs capacity`.
- **Ein neuer Agent braucht einen Neustart von Claude Code** (siehe oben).
- **Anmelden** muss man in jedem Werkzeug selbst (`agy`, `codex login`, `opencode auth login`); die Ansicht zeigt nur den Zustand. Auth-Dateien werden auf Vorhandensein geprüft, nie gelesen.

---

## English

One interactive Claude Code window acts as the **supervisor**: it hands reviews, second opinions and bounded analyses to other AI CLIs (Codex, Antigravity/Gemini, OpenCode/Kimi) and then checks every returned finding against the code itself. The bridge is a set of small **wrapper agents** in `~/.claude/agents/` that only forward one CLI call. `sccs agents` sets those wrappers up and keeps them tidy.

**`sccs agents` is configuration only.** It never starts, dispatches or monitors agent work, never installs the CLIs (that is `sccs doctor`) and never logs in (each tool does that itself).

### 1. Configure

```fish
sccs agents                              # terminal: full-screen view
sccs agents list [--json]                # table: agent, tool, model, mode
sccs agents tools [--json]               # installed? version, login, default model, config path
sccs agents models <tool> [--json]       # models the tool itself reports
sccs agents adopt <name> [--yes]         # take over a hand-written wrapper
sccs agents new <tool> <name> [--model M]    # create a new read-only wrapper
sccs agents set-model <name> <model>     # change a managed wrapper's model
```

`<tool>` is `agy` (Antigravity, always a Gemini model), `opencode` or `codex`. Pi has no tested template yet; `sccs agents new pi …` exits with „Pi has no tested wrapper template yet.“. Without a terminal (pipe, script) `sccs agents` prints the table instead of the full-screen view.

**Full-screen view.** The supervisor on top (Claude Code, session model, agent folder), then one row per agent carrying the state of its tool, so a broken tool shows up at the agent it disables. Tools without an agent appear as a dimmed row. The line below explains the selected agent (how read-only is enforced, whether export is off).

| Key | Effect |
|---|---|
| Enter or `m` | pick a model (from the tool's real model list), or adopt a wrapper that is not adopted yet |
| `n` | create a new wrapper |
| `w` | tools view: version, login, default model, config path, pointer to `sccs doctor` |
| `?` | this guide |
| `r` | reload |
| `q` | quit |

**The Mode column** reads `read-only` for wrappers sccs manages; `read-only (not adopted)` for a hand-written wrapper whose command shape sccs recognises but has not adopted yet; `unmanaged` for an agent matching no template (sccs never writes it); `plugin` for agents shipped by plugins (for example `codex:codex-rescue`, display only). A trailing `€` means every call costs OpenRouter credit.

**Adopt existing wrappers.** `sccs agents adopt antigravity-worker` (or Enter in the view) asks once, then inserts only an `sccs:` block into the frontmatter and leaves the rest of the file byte for byte as it was (CRLF and BOM included). Afterwards `set-model` works. `--yes` skips the question; with `--json`, `--yes` is required.

**Change a model.** `sccs agents set-model antigravity-worker gemini-4-argon-high` edits only the model in the wrapper's command line, not the description and not the prompt text. The wrapper's own model (`model: haiku`) stays fixed: the wrapper only forwards. The model is checked against the tool's model list; if the list cannot be read (offline, logged out) a well-formed name is accepted with a warning and shown as `unverified`. For Antigravity the name must start with `gemini-`. A name may contain only letters, digits and `. _ : / ~ -` and must not start with `-`.

**New wrapper.** `sccs agents new opencode review-worker --model openrouter/some-model` creates `~/.claude/agents/review-worker.md` from the bundled template, always read-only. The name is lowercase letters, digits and `-`, no `/`, no `.md`. An existing file is never overwritten. **Restart Claude Code afterwards**, or the running session does not know the agent.

**Why `Export: off`.** `~/.claude/agents` is synced by sccs, and `sccs integrations codex|opencode|pi` exports agents into other tools. A wrapper that says „call `opencode run`“ does not belong there: it would reappear as an agent inside OpenCode or Codex and call itself. On create and adopt, sccs therefore adds the name to `opencode.exclude`, `pi.exclude` and `codex.exclude` in `config.yaml` (once, with a backup). When all three hold the name, the view shows `Export: off`. The wrapper itself still syncs between your machines; on a host without the tool, the row shows the missing CLI.

### 2. Work

1. Open a terminal window (for example a Herdr window) and change into the project:

   ```fish
   cd ~/gitbase/my-project
   claude
   ```

2. Ask for work the way you would say it:

   - „Lass den Diff von Codex, Gemini und Kimi prüfen und gleiche die Befunde am Code ab“ (have Codex, Gemini and Kimi review the diff and reconcile the findings against the code)
   - „Hol eine zweite Meinung von Gemini zu diesem Entwurf“ (get a second opinion from Gemini on this draft)

3. The supervisor starts the wrappers **in the background**, keeps working, and is notified when a worker finishes. It marks every finding as an **unverified claim** of the model that made it, checks each one against the code and reports which held and which did not.

A Claude Code session that was already running does not see newly created agents: quit and start it again.

### 3. Running, done, stuck

- **Running:** the supervisor gets no answer until the worker finishes and keeps working meanwhile. A Gemini review of a diff of about 300 lines takes roughly four minutes.
- **Done:** Claude Code announces the end of the background job; the supervisor reads the result and checks it.
- **Stuck:** every call carries an outer `timeout 900` (15 minutes). A worker that ends with **exit 124** got a task that was too large. Split it (one call per file or directory; never a diff of more than about 2,000 lines in one piece) instead of waiting longer.

### 4. Traps

- **Codex' own sandbox is not nono.** An `EPERM` on `/tmp/xcrun_db…` inside a Codex run is Codex' `read-only` sandbox doing its job. Skip it and carry on with reading tools; do not ask for a restart of the nono session.
- **Gemini needs the material in the prompt.** Headless, Antigravity cannot ask for permission; every command outside the allowlist is denied and the run ends with `jetski: no output produced`. The wrapper therefore puts the diff or the excerpts into the prompt. If you see that message, material was missing.
- **OpenCode costs OpenRouter credit** per call (marked `€`). An error about credit or login is reported, not retried with another provider.
- **Free `opencode/*` models are not for customer data.** Their data policy is unclear; the wrapper passes it on if asked, but says so in its answer.
- **A Gemini wrapper stays on Gemini.** Antigravity also resells Claude and GPT models; falling back to one of them would be a self-review. If no Gemini model works, the wrapper says so and stops. The same rule stands behind `sccs capacity`.
- **A new agent needs a Claude Code restart** (see above).
- **Logging in** is done in each tool itself (`agy`, `codex login`, `opencode auth login`); the view only shows the state. Auth files are checked for presence and never read.
