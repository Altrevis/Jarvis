---
name: desktop-app
description: >-
  Builds, packages or reviews a desktop app for Windows, macOS and Linux:
  framework decision table (Qt via PySide6/PyQt6, Electron, Tauri, .NET
  WPF/WinUI/Avalonia, GTK, Tkinter) by language, footprint, look and licence;
  a UI thread that never blocks (workers, QThread, async, secure Electron IPC);
  OS integration and per-OS data folders; HiDPI, accessibility, logs and
  crashes; packaging, installers, code signing, notarisation and auto-update.
  Use for a desktop app or an installer. Se déclenche sur : application de
  bureau, logiciel Windows, PyQt, PySide, Electron, Tauri, installeur,
  exécutable, packaging.
---

# desktop-app
Produces code in the target folder and `desktop-plan.md` (framework choice,
architecture, OS integration, packaging per OS, signing and update plan,
tests). GUI runs, installer builds on each OS, signing and notarisation are
the user's steps.

## Before you start
| Input | Where | If missing |
|---|---|---|
| Features, users, platforms | task, handoffs (spec, design) | Windows, macOS and Linux; core features only |
| Existing app | entry point (`main.py`, `package.json` `main`, `*.csproj`, `src-tauri/`), framework imports | choose with the table below |
| Language preference | task, team | Python → PySide6; web skills → Tauri or Electron |
| Distribution | task: internal, open source, commercial, store | direct download, unsigned for testing, signing plan for release |
| Licence constraints | task | flag GPL implications before choosing PyQt |

## Method
1. **Choose** the framework (table) or keep the existing one; record why.
2. **Structure**: UI layer (windows, widgets or components) separate from the
   core (logic, services, storage) so the core is testable without a GUI.
3. **Threading**: list every slow operation; run each in a worker (pattern per
   framework below) and report back to the UI through signals, events or IPC.
4. **OS integration**: settings and data folders, file dialogs, drag and drop,
   notifications, tray, autostart (opt-in), single-instance lock, file
   associations if asked.
5. **Robustness**: logging to a rotating file in the data folder; unhandled
   exceptions caught, logged and shown in a readable dialog; settings
   migrated between versions.
6. **HiDPI and accessibility**: scalable layouts, vector or multi-resolution
   icons, keyboard navigation, accessible names, system theme (light/dark).
7. **Tests**: core unit tests (`python3 -m pytest`, `npm test`); GUI tests
   (pytest-qt, Playwright for Electron) written for the user if they need a
   display.
8. **Packaging** per OS (checklist), with the commands for the user and the
   OS each one must run on.
9. **Signing, notarisation, updates**: the plan and the secrets to create.
10. **Write** `desktop-plan.md`.

## Checklists

### Framework choice
| Framework | Language | Footprint | Look | Licence notes | Fits |
|---|---|---|---|---|---|
| Qt via PySide6 | Python | medium | native-like widgets, QML | LGPL (Qt for Python) | Python tools with a real UI |
| Qt via PyQt6 | Python | medium | same as above | GPL or commercial licence | GPL projects, existing PyQt code |
| Electron | JS/TS + HTML/CSS | large (bundles Chromium and Node) | web | MIT | web teams, rich UIs, many integrations |
| Tauri | Rust core + web front-end | small (system webview) | web | MIT/Apache-2.0 | light apps from web skills |
| WPF / WinUI | C# | medium | Windows-native | MIT (open-source parts) | Windows-only business apps |
| Avalonia | C# | medium | own rendering, cross-platform | MIT | .NET teams needing macOS and Linux |
| GTK | C, Python, Rust... | small to medium | native on GNOME | LGPL | Linux-first apps |
| Tkinter | Python | small (in the standard library) | basic | Python licence | small internal tools |

### Keeping the UI responsive
| Framework | Pattern |
|---|---|
| Qt | `QThread` + worker `QObject` moved to it, or `QThreadPool` + `QRunnable`; results back by signals (queued connections); never touch widgets from a worker |
| Electron | heavy work in the main process or a worker/utility process; renderer talks through a preload `contextBridge` API and `ipcRenderer.invoke`; `contextIsolation: true`, `nodeIntegration: false`, `sandbox` on |
| Tauri | Rust commands (`#[tauri::command]`, async) called with `invoke`; capabilities/allowlist minimal |
| .NET | `async`/`await` with `Task.Run` for CPU work; `Dispatcher` / `DispatcherQueue` to update the UI |
| Tkinter | `threading` + a `queue.Queue` polled with `after()` |

### Data and settings folders
| OS | Config / data |
|---|---|
| Windows | `%APPDATA%\<App>` (roaming), `%LOCALAPPDATA%\<App>` (caches, logs) |
| macOS | `~/Library/Application Support/<App>`, caches in `~/Library/Caches/<App>`, logs in `~/Library/Logs/<App>` |
| Linux | `$XDG_CONFIG_HOME/<app>` (default `~/.config`), `$XDG_DATA_HOME/<app>` (default `~/.local/share`), `$XDG_CACHE_HOME` |
Qt: `QStandardPaths`; Electron: `app.getPath('userData')`; Python without Qt:
the `platformdirs` package if installed, else these rules.

### Packaging and installers
| Tool | Produces | Note |
|---|---|---|
| PyInstaller | one-folder or one-file executable | build on each target OS; one-file starts slower; add data files and Qt plugins explicitly when needed |
| Nuitka | compiled executable | longer builds, often faster start |
| Briefcase (BeeWare) | native installers per OS | opinionated project layout |
| electron-builder | NSIS/MSI, DMG, AppImage, deb, rpm | auto-update support |
| Tauri bundler | MSI/NSIS, DMG/app, AppImage, deb, rpm | small installers |
| Windows | MSI or MSIX; MSIX for the Microsoft Store | |
| macOS | `.app` in a DMG; universal or per-architecture builds | notarisation required for smooth Gatekeeper |
| Linux | AppImage (portable), Flatpak (sandboxed, Flathub), deb/rpm | |

### Signing and updates
- Windows: Authenticode code-signing certificate; unsigned apps trigger
  SmartScreen warnings.
- macOS: Developer ID Application certificate, hardened runtime, then
  notarisation with `notarytool` and stapling — all on a Mac, by the user.
- Linux: signed repositories or Flatpak; AppImage can carry a signature.
- Auto-update over HTTPS with signed update metadata; staged rollout; a
  way to roll back.

## Deliverable
Code in the target folder, and `desktop-plan.md` in the shared work folder
(translate the headings into the user's language):

```markdown
# Desktop plan — <app>
## Summary
## Framework choice
| Criterion | Decision | Why |
## Architecture
<UI / core split; threads and workers; Mermaid diagram if useful>
## OS integration
| Feature | Windows | macOS | Linux |
## Robustness (logs, crashes, settings migration)
## Accessibility and HiDPI
## Tests
| Level | Command | Result (as run / for the user) |
## Packaging (for the user)
| OS | Tool | Command | Must run on | Output |
## Signing and updates
## Decisions
## Next steps
```

## Pitfalls
- Network or file scans on the UI thread: the window freezes ("not
  responding").
- Updating widgets from a worker thread (crashes or undefined behaviour in Qt).
- Writing settings next to the executable or in the install folder.
- Electron with `nodeIntegration: true` loading remote content.
- Choosing PyQt for a closed-source product without a commercial licence.
- Expecting PyInstaller on Linux to produce a Windows `.exe` (build per OS).
- Forgetting Qt plugins or data files in the bundle: the app starts on the
  developer machine only.
- Hardcoded path separators and drive letters.
