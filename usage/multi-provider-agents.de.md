# Mit Agenten mehrerer Anbieter arbeiten: Schritt-für-Schritt-Einrichtung (sccs 2.73.0)

[Deutsch](multi-provider-agents.de.md) · [English](multi-provider-agents.en.md)

Diese Anleitung richtet in zwölf Schritten ein, dass **Claude Code** (Anthropic) Reviews, zweite Meinungen und begrenzte Analysen an **Gemini** (Google), **Kimi** (Moonshot über OpenRouter) und **Codex** (OpenAI) weiterreicht und jeden Befund selbst am Code prüft. Sie richtet sich an Leser, die in der Shell zu Hause sind und sccs nicht kennen.

## Das Prinzip in fünf Sätzen

- **sccs** (SkillsCommandsConfigsSync) ist ein Kommandozeilenwerkzeug, das Claude-Code-Dateien (Skills, Agenten, Befehle, Hooks) zwischen Rechnern synchronisiert. Seit 2.73.0 hat es den Befehl `sccs agents`.
- Ein interaktives Claude-Code-Fenster ist der **Supervisor** (Aufseher): Er verteilt Aufträge und wertet aus.
- Die Brücke zu anderen Anbietern sind **Wrapper-Agenten**: kleine Dateien in `~/.claude/agents/`, die nur einen einzigen CLI-Aufruf weiterreichen (`agy`, `opencode run` oder `codex exec`). Sie laufen auf dem kleinsten Claude-Modell, haben nur die Werkzeuge `Bash` und `Read` und sind **immer schreibgeschützt**.
- Ein Befund eines fremden Modells gilt als **ungeprüfte Behauptung**. Der Supervisor prüft jeden einzeln am Code und berichtet, welche standgehalten haben.
- `sccs agents` ist **reine Konfiguration**: Es startet keine Agentenarbeit, installiert keine CLIs und meldet nirgends an. Den Terminal-Multiplexer **Herdr** nutzen Sie nur als Fenster; er gehört nicht zur Konfiguration. Ein eigener Orchestrator (CAO) ist nicht beteiligt.

## Die beteiligten Anbieter

| Anbieter | Werkzeug (CLI) | Vorlage für `sccs agents new` | Anmerkung |
|---|---|---|---|
| Anthropic | Claude Code (`claude`) | – | Supervisor, kein Wrapper nötig |
| Google | Antigravity CLI (`agy`) | `agy` | nur `gemini-*`-Modelle |
| Moonshot (Kimi) über OpenRouter | OpenCode CLI (`opencode`) | `opencode` | kostet OpenRouter-Guthaben pro Aufruf |
| OpenAI | Codex CLI (`codex`) | `codex` | zusätzlich das Claude-Code-Plugin `codex@openai-codex` |
| Pi | `pi` | keine | wird nur angezeigt |

## Konfiguration in zwölf Schritten

Alle Snippets sind Fish-Syntax. Mit „Annahme“ markierte Stellen konnte ich nicht gegen die echte Hilfe prüfen.

### 1. sccs 2.73.0 installieren oder aktualisieren

Voraussetzung ist [uv](https://docs.astral.sh/uv/).

```fish
uv tool install sccs        # erstmalig
uv tool upgrade sccs        # vorhandene Installation
sccs --version
```

**Erfolg:** `sccs, version 2.73.0` (oder höher).

### 2. Die Werkzeuge installieren und prüfen

`sccs doctor` prüft Node.js, die `claude`-CLI und die konfigurierten Claude-Plugins (darunter `codex@openai-codex`) und installiert fehlende Teile nach Rückfrage. Die drei Fremd-CLIs `agy`, `opencode` und `codex` installiert es **nicht**; die richten Sie nach der Anleitung des jeweiligen Anbieters ein (Annahme: Installationsbefehle sind anbieterabhängig und hier nicht geprüft).

```fish
sccs doctor check               # nur lesen: Tabelle mit Status je Bestandteil
sccs doctor install             # fehlende Plugins/Werkzeuge installieren, je Aktion mit Rückfrage
```

Fehlt das Codex-Plugin, lässt es sich auch von Hand holen (Hilfe geprüft, die Marktplatz-Quelle `openai/codex-plugin-cc` steht in der Doctor-Tabelle):

```fish
claude plugin list
claude plugin install codex@openai-codex
```

**Erfolg:** `sccs doctor check` zeigt Node.js, Claude CLI und `codex@openai-codex` als `OK`. Ob die drei Fremd-CLIs vorhanden sind, zeigt erst Schritt 4.

### 3. Bei jedem Anbieter anmelden

Anmelden muss man in jedem Werkzeug selbst; `sccs` zeigt nur den Zustand.

```fish
claude                     # Claude Code: beim ersten Start anmelden
codex login                # OpenAI; Zustand prüfen mit: codex login status
opencode auth login        # OpenCode: Anbieter OpenRouter wählen und den Schlüssel eingeben
opencode auth list         # eingetragene Anbieter ansehen
agy                        # Antigravity: einmal interaktiv starten und anmelden
```

`codex login` kennt außerdem `--with-api-key` (Schlüssel von der Standardeingabe). Für `opencode auth login` ist die Wahl „OpenRouter“ im Dialog eine Annahme; die Hilfe nennt nur den optionalen Parameter `url`. Für `agy` gibt es laut `agy --help` keinen eigenen Anmeldebefehl; das Starten ohne Argumente zum Anmelden ist eine Annahme, gestützt auf die Fehlermeldung des Wrappers („the user must run `agy` once interactively“).

**Erfolg:** `codex login status` und `opencode auth list` melden einen angemeldeten Zugang. `agy -p "Antworte mit OK"` antwortet statt einen Authentifizierungsfehler zu melden.

### 4. Zustand ansehen

```fish
sccs agents                # Terminal: Vollbild-Ansicht; in Pipe/Skript: Tabelle
sccs agents tools          # welche CLIs installiert sind, Version, Login, Standardmodell
sccs agents list           # alle Agenten in ~/.claude/agents mit Werkzeug, Modell und Modus
```

Die Spalte **Installed** zeigt `yes` oder `no`. In **Login** bedeutet `yes`: eine Anmelde-Datei ist vorhanden (sie wird nie gelesen); `unknown`: nicht erkennbar, die Anmeldung kann auch im Schlüsselbund oder in Umgebungsvariablen liegen. Die Spalte **Mode** nennt `read-only` (von sccs verwaltet), `read-only (not adopted)` (handgeschriebener Wrapper, noch nicht übernommen), `unmanaged` (passt zu keiner Vorlage, sccs schreibt ihn nie) oder `plugin` (zum Beispiel `codex:codex-rescue`, nur Anzeige). Ein angehängtes `€` bedeutet: jeder Aufruf kostet OpenRouter-Guthaben.

**Erfolg:** Jedes Werkzeug, das Sie nutzen wollen, steht auf `Installed: yes`. Pi darf `no` sein.

### 5. Wrapper übernehmen oder neu anlegen

**a) Vorhandene handgeschriebene Wrapper übernehmen.** Zeigt `sccs agents list` einen Wrapper als `read-only (not adopted)`:

```fish
sccs agents adopt antigravity-worker
sccs agents adopt opencode-worker
```

sccs fragt einmal nach, fügt nur einen `sccs:`-Block in den Frontmatter ein und lässt den Rest der Datei Byte für Byte unverändert. Mit `--yes` entfällt die Rückfrage.

**b) Neue Wrapper anlegen.** Name: Kleinbuchstaben, Ziffern und `-`, ohne `/` und ohne `.md`.

```fish
sccs agents new agy gemini-review
sccs agents new opencode kimi-review --model openrouter/~moonshotai/kimi-latest
sccs agents new codex codex-review
```

Ohne `--model` gilt der Standard der Vorlage: `gemini-4-argon-high` für `agy`, `openrouter/~moonshotai/kimi-latest` für `opencode`, bei `codex` das Standardmodell aus `~/.codex/config.toml`; steht dort keines, bricht `new` mit „No default Codex model in ~/.codex/config.toml; pass --model.“ ab. Eine vorhandene Datei wird nie überschrieben. Pi hat keine Vorlage: `sccs agents new pi …` bricht mit „Pi has no tested wrapper template yet.“ ab.

**Erfolg:** Die Datei `~/.claude/agents/<name>.md` existiert, und `sccs agents list` zeigt den Agenten als `read-only`.

### 6. Modelle wählen

```fish
sccs agents models agy             # Modelle, die das Werkzeug selbst meldet
sccs agents models opencode
sccs agents models codex
sccs agents set-model gemini-review gemini-4-argon-high
```

`set-model` ändert nur das Modell in der Befehlszeile des Wrappers. Das Modell des Wrappers selbst (`model: haiku`) bleibt fest. Regeln:

- **`agy`: nur `gemini-*`.** Antigravity verkauft auch Claude- und GPT-Modelle weiter; auf eines davon auszuweichen wäre Selbstreview. Geht kein Gemini-Modell, meldet der Wrapper das und hört auf.
- **Freie `opencode/*`-Modelle** lösen eine Warnung aus („Free opencode/* models have an unclear data policy — not for code with customer data.“): nicht für Code mit Kundendaten.
- **`unverified`:** Lässt sich die Modellliste nicht lesen (offline, nicht angemeldet), nimmt sccs einen formal gültigen Namen mit Warnung an und zeigt ihn als `unverified`.
- Der Name darf nur Buchstaben, Ziffern und `. _ : / ~ -` enthalten und nicht mit `-` beginnen.

Dasselbe geht in der Vollbild-Ansicht: Enter oder `m` wählt aus der echten Modellliste des Werkzeugs.

**Erfolg:** `sccs agents list` zeigt das gewählte Modell; bei lesbarer Liste ohne `unverified`.

### 7. Export-Ausschluss prüfen

`~/.claude/agents` wird synchronisiert, und `sccs integrations codex|opencode|pi` exportiert Agenten in andere Werkzeuge. Ein Wrapper, der „rufe `opencode run` auf“ sagt, würde dort wieder als Agent auftauchen und sich selbst aufrufen. Beim Anlegen und Übernehmen trägt sccs den Namen deshalb einmalig (mit Sicherung der Konfiguration) unter `opencode.exclude`, `pi.exclude` und `codex.exclude` in `~/.config/sccs/config.yaml` ein.

```fish
sccs agents                              # in der Ansicht: die Zeile unter der Tabelle zeigt „Export: off“
sccs integrations sync-all --dry-run     # Plan ansehen, schreibt nichts
```

**Erfolg:** Der gewählte Agent zeigt `Export: off`, und der Plan von `sync-all --dry-run` enthält keinen Ihrer Wrapper.

### 8. Claude Code neu starten

Eine bereits laufende Sitzung kennt neu angelegte Agenten nicht. Beenden Sie Claude Code und starten Sie es neu (Schritt 10 zeigt den Start).

**Erfolg:** Im neuen Claude-Code-Fenster erscheinen die Wrapper unter den verfügbaren Agenten (Befehl `/agents`).

### 9. Auf weiteren Rechnern bereitstellen

Die Wrapper-Dateien liegen in der Kategorie `claude_agents` (lokal `~/.claude/agents`) und reisen mit dem normalen Sync mit.

```fish
sccs sync --dry-run -c claude_agents          # Vorschau auf Rechner A (Quelle)
sccs sync --commit --push -c claude_agents    # veröffentlichen
sccs sync --pull -c claude_agents             # auf Rechner B: holen und anwenden
sccs agents                                   # auf Rechner B: Zustand prüfen
```

Auf Rechner B müssen die CLIs selbst installiert und angemeldet sein (Schritte 2 und 3); sonst zeigt die Zeile des Wrappers den fehlenden Zustand des Werkzeugs. Die Ausschlusslisten stehen in der `config.yaml`; ob sie auf Rechner B ankommen, hängt davon ab, wie Sie diese Datei verteilen (Annahme). Kontrollieren Sie dort `Export: off` wie in Schritt 7.

**Erfolg:** `sccs agents list` auf Rechner B zeigt die Wrapper; `Installed: yes` für die dort genutzten Werkzeuge.

### 10. In Herdr mit Claude starten

Öffnen Sie ein Terminalfenster (zum Beispiel ein Herdr-Fenster), wechseln Sie ins Projekt und starten Sie Claude Code:

```fish
cd ~/gitbase/mein-projekt
claude
```

**Erfolg:** Claude Code startet im Projekt; die Wrapper sind verfügbar (Schritt 8).

### 11. Mit Beispielaufträgen arbeiten

Stellen Sie Aufträge, wie Sie sie sagen würden:

- „Lass den Diff von Codex, Gemini und Kimi prüfen und gleiche die Befunde am Code ab“
- „Hol eine zweite Meinung von Gemini zu diesem Entwurf“
- „Lass Codex über `codex:codex-rescue` die Ursache dieses Fehlers untersuchen“ (Agent aus dem Plugin; `/codex:review` startet einen Codex-Review direkt)

Der Supervisor startet die Wrapper **im Hintergrund**, arbeitet weiter und wird benachrichtigt, wenn ein Worker fertig ist. Jeden Befund kennzeichnet er als ungeprüfte Behauptung des jeweiligen Modells, prüft ihn einzeln am Code und berichtet, welche standgehalten haben. Ein Gemini-Review eines Diffs von rund 300 Zeilen dauert etwa vier Minuten.

**Erfolg:** Sie erhalten eine Liste von Befunden je Modell mit dem Ergebnis der Prüfung am Code.

### 12. Fehlerbilder

- **`jetski: no output produced`** (Gemini): Headless kann Antigravity keine Rückfrage stellen, jeder Befehl außerhalb der Erlaubnisliste wird abgelehnt. Es fehlte Material im Prompt; der Wrapper legt Diff oder Auszüge deshalb in den Prompt. Auftrag mit dem Material erneut stellen.
- **Exit 124:** Der äußere `timeout 900` (15 Minuten) hat zugeschlagen, die Aufgabe war zu groß. Aufteilen: ein Aufruf je Datei oder Verzeichnis, Diffs über etwa 2000 Zeilen nie am Stück.
- **`EPERM` auf `/tmp/xcrun_db…` in einem Codex-Lauf:** Das ist Codex' eigene `read-only`-Sandbox bei der Arbeit, **nicht** die nono-Sandbox. Weglassen und mit lesenden Mitteln weitermachen; keinen Neustart der nono-Sitzung verlangen.
- **Guthaben oder Anmeldung (OpenCode, Codex, Gemini):** Der Wrapper meldet den Fehler und wiederholt nicht mit einem anderen Anbieter. Guthaben bei OpenRouter aufladen beziehungsweise Schritt 3 für das Werkzeug wiederholen; `sccs agents tools` zeigt den Login-Zustand.
- **Neuer Agent fehlt in der Sitzung:** Claude Code neu starten (Schritt 8).

## Tasten der Vollbild-Ansicht

| Taste | Wirkung |
|---|---|
| Enter oder `m` | Modell wählen bzw. nicht übernommenen Wrapper übernehmen |
| `n` | neuen Wrapper anlegen |
| `w` | Werkzeug-Ansicht (Version, Login, Standardmodell, Config-Pfad) |
| `?` | Hilfe; `Tab` wechselt zwischen „Anleitung“ und „Vorgehen“ |
| `r` | neu einlesen |
| `q` | beenden |

## Weiterführend

- Referenz zu allen Unterbefehlen, Modi und Fallen: [docs/usage/agents.md](../docs/usage/agents.md)
- Warum es so gebaut ist (Supervisor, schreibgeschützte Wrapper, kein Orchestrator, Gemini bleibt bei Gemini): [Abschnitt „Supervisor und Wrapper-Agenten“ in docs/architecture.md](../docs/architecture.md#supervisor-und-wrapper-agenten)
