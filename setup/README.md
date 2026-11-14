# Claude-Code-Setup (global)

Diese Anleitung ist für alle, die dieses Claude-Code-Setup auf einem neuen Rechner einrichten.

Das Setup folgt dem Harness-Engineering-Ansatz von HumanLayer: schlank starten und nur das Nötige installieren.

- **Projektteil:** `CLAUDE.md`, `agent_docs/`, der Stop-Hook in `.claude/settings.json` und `scripts/check.*` liegen bereits im Repo. Wer das Template nutzt, bekommt sie automatisch.
- **Globaler Teil:** Er liegt in `setup/claude-global/` und muss auf jedem Rechner einmal nach `~/.claude/` kopiert werden.

## Inhalt

| Pfad | Was | Herkunft |
|---|---|---|
| `claude-global/commands/research_codebase.md` | `/research_codebase`: Code dokumentieren, Ergebnis in `docs/research/` | HumanLayer, generisch umgeschrieben |
| `claude-global/commands/create_plan.md` | `/create_plan`: Plan in Phasen, Ablage in `docs/plans/` | HumanLayer, generisch umgeschrieben |
| `claude-global/commands/implement_plan.md` | `/implement_plan`: Plan Phase für Phase umsetzen und verifizieren | HumanLayer, generisch umgeschrieben |
| `claude-global/commands/iterate_plan.md` | `/iterate_plan`: bestehenden Plan überarbeiten | HumanLayer, generisch umgeschrieben |
| `claude-global/commands/create_handoff.md` | `/create_handoff`: Übergabe-Dokument in `docs/handoffs/` | HumanLayer, generisch umgeschrieben |
| `claude-global/commands/resume_handoff.md` | `/resume_handoff`: aus einem Handoff weiterarbeiten | HumanLayer, generisch umgeschrieben |
| `claude-global/skills/improve-claude-md/` | CLAUDE.md mit `<important if>`-Blöcken verbessern | `humanlayer/skills` @ `4d69d20`, unverändert |
| `claude-global/skills/web-design-guidelines/` | UI-Code gegen die Web Interface Guidelines prüfen | `vercel-labs/agent-skills` @ `1a2c79d`, unverändert |

**Was „generisch umgeschrieben“ heißt:** Basis sind die `_nt`-Varianten aus `humanlayer/humanlayer/.claude/commands` @ `99abe67`. Das ist der letzte Stand vor dem Entfernen in Commit `d8197ba` am 22.10.2026. Geändert wurde:
- Statt der HumanLayer-Subagents nutzen die Commands Standard-`general-purpose`-Agents. Research-Subagents laufen mit `model: sonnet`.
- Artefakte landen in `./docs/research`, `./docs/plans` und `./docs/handoffs` des jeweiligen Projekts.
- thoughts-Sync, Linear und `make` sind entfernt.

## Auf einem neuen Rechner einrichten

Voraussetzungen: Claude Code, git und gh. Für SkillSpector außerdem [uv](https://docs.astral.sh/uv/), für `npx skills` Node.js.

**Bestehende Dateien:** Prüfe vorher, ob in `~/.claude/commands` oder `~/.claude/skills` schon Dateien mit gleichem Namen liegen.
- Die PowerShell-Variante überschreibt sie ohne Nachfrage.
- Die bash-Variante fragt bei Commands nach (`cp -i`), überschreibt Skill-Ordner aber ebenfalls.

**Windows (PowerShell), im Repo-Root:**
```powershell
New-Item -ItemType Directory -Force "$HOME\.claude\commands", "$HOME\.claude\skills" | Out-Null
Copy-Item setup\claude-global\commands\*.md "$HOME\.claude\commands\"
Copy-Item -Recurse -Force setup\claude-global\skills\* "$HOME\.claude\skills\"
```

**macOS, Linux oder Git Bash, im Repo-Root:**
```bash
mkdir -p ~/.claude/commands ~/.claude/skills
cp -i setup/claude-global/commands/*.md ~/.claude/commands/
cp -R setup/claude-global/skills/* ~/.claude/skills/
```

**Prüfen:** Starte Claude Code neu. Die Commands (`/research_codebase` usw.) und Skills (`improve-claude-md`, `web-design-guidelines`) sollten in der Liste erscheinen.

**Neues Projekt aus dem Template anlegen:**
```bash
gh repo create <name> --template adriannoahwimmer/hackathon-starter --private --clone
```

## SkillSpector (vor jeder Installation fremder Skills)

```bash
uv tool install git+https://github.com/NVIDIA/skillspector.git    # getestet: v2.12.0
skillspector scan <skill-ordner> --no-llm --format json > report.json
```
- Unter Windows funktioniert `--output` nicht. Den Report deshalb wie oben über stdout umleiten.
- Installiert wird nur bei `recommendation: SAFE`. Danach prüfen, dass der installierte Inhalt identisch mit der gescannten Version ist: Git-Blob-Hash per `git hash-object` gegen `git rev-parse HEAD:<pfad>` im Klon.
- Die CLI wird ohne Telemetrie aufgerufen und auf eine Version gepinnt: `DO_NOT_TRACK=1 npx -y skills@1.8.1 add <repo> --skill <name> -g -a claude-code -y --copy`

### Ergebnisse (statischer Scan `--no-llm`, 13.–14.11.2026)

| Quelle | Score | Empfehlung | Befunde | Abdeckung | Installiert |
|---|---|---|---|---|---|
| improve-claude-md (`humanlayer/skills` @ `4d69d20`) | 0 | SAFE | 0 | 100 % | ja |
| web-design-guidelines (`vercel-labs/agent-skills` @ `1a2c79d`) | 0 | SAFE | 0 | 100 % | ja |
| Remote-Regeln von web-design-guidelines (`command.md` @ `434b7f9`) | 0 | SAFE | 0 | 100 % | (wird live geladen) |
| HumanLayer-Commands, Originale (11 Dateien @ `99abe67`) | 0 | CAUTION | 0 | 64 % | nur als Vorlage genutzt |
| generische Commands (dieser Ordner) | 0 | SAFE | 0 | 100 % | ja |
| taste-skill (`Leonxlnx/taste-skill` @ `f6b7657`) | 84 | DO_NOT_INSTALL | 19 (17 HIGH, 2 MEDIUM) | 2,7 % | **nein** |

**HumanLayer-Originale (CAUTION):** Die Einstufung kommt nur von der unvollständigen Abdeckung. In 4 Dateien konnte der Parser die Codeblock-Beispiele nicht vollständig auflösen. Diese Stellen wurden von Hand gelesen: harmloser Prompt-Text.

**web-design-guidelines:** Der Skill lädt bei jeder Nutzung seine Regeln und Ausgabe-Anweisungen ungepinnt von `raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md`. Gescannt wurde nur der damalige Stand. Spätere Änderungen an dieser Datei deckt der Scan nicht ab.

**taste-skill (nicht installiert):**
- 15× AE1: referenzierte Dateien (`consistency.mjs`, `sections.md`) nur teilweise analysiert
- 2× P2: HTML-Kommentar in Beispiel-READMEs, vermutlich Fehlalarm
- LP3: keine `allowed-tools`-Deklaration trotz Env-, Netzwerk- und Shell-Zugriff
- RP1: nicht gepinntes `npx skills`

Ein klarer Schadcode-Befund war nicht dabei. Allerdings wurden 1.440 von 1.480 Dateien nur teilweise geprüft, darunter ausführbare Node-Skripte. Vor einer Installation sollte ein Scan mit LLM-Analyse laufen, z. B. mit `SKILLSPECTOR_PROVIDER=claude_cli`.

## Nicht Teil dieses Setups
- SkillSpector selbst: wird per `uv tool` installiert, siehe oben.
- Andere globale Skills, die schon vorher auf dem Rechner lagen.
- `~/.claude/settings.json`: unverändert. Bewusst keine MCP-Server und kein everything-claude-code.
