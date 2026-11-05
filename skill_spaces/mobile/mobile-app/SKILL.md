---
name: mobile-app
description: >-
  Plans, builds or reviews a mobile app for iOS and Android: native
  (SwiftUI, Jetpack Compose) versus cross-platform (React Native with Expo,
  Flutter) decision table, architecture with navigation, state, API layer,
  offline storage and sync, platform guidelines, permissions and privacy
  declarations, push notifications, accessibility, performance, tests and a
  device matrix, and the signing and release path through TestFlight and
  Google Play. Use for a mobile app or a store release. Se déclenche sur :
  application mobile, app iOS, app Android, React Native, Flutter, Expo,
  publier sur l'App Store, notifications push.
---

# mobile-app
Produces `mobile-plan.md` (choice, architecture, screens, offline and sync,
permissions and privacy, accessibility, tests, release steps) and/or code in
the target folder. Emulators, devices, signing and store uploads are the
user's steps.

## Before you start
| Input | Where | If missing |
|---|---|---|
| Features and users | task, handoffs (spec, design) | the core flow only; record it |
| Platforms | task | iOS and Android |
| Existing project | `package.json` (`react-native`, `expo`), `pubspec.yaml`, `*.xcodeproj`, `build.gradle(.kts)` | choose with the table below |
| API | web or architecture handoff | define the calls the app needs and note them for the web specialist |
| Team skills | task | JavaScript/TypeScript → React Native with Expo |
| Device features | task: camera, location, Bluetooth, background work | none |

## Method
1. **Choose** (table below); record the reasons under Decisions.
2. **Screens and navigation**: screen inventory from the design handoff;
   navigation structure (tabs, stacks, modals); deep links if needed.
3. **Architecture**: UI → state (a store or view models) → repository → API
   client and local storage; side effects out of UI components; types for API
   payloads.
4. **Offline and sync**: which data is cached; local database (SQLite-based,
   or the platform's store); queue of local changes; sync on reconnect; the
   conflict rule (last write wins, server wins, or merge per field) written
   down.
5. **Permissions**: request in context, just before the feature needs it;
   handle "denied" and "denied forever" (point to settings).
6. **Push notifications**: APNs for iOS and Firebase Cloud Messaging for
   Android (or the cross-platform library over them); device token sent to the
   back-end; notification permission asked after showing the value.
7. **Accessibility and performance** per the checklists.
8. **Tests**: unit tests for logic; component tests; UI tests (XCUITest,
   Espresso or Compose testing, Detox or Maestro, Flutter integration tests)
   written for the user to run; a device and OS-version matrix.
9. **Run what you can**: `npm ci`, `npm test`, `npx tsc --noEmit`,
   `npx expo-doctor` (Expo projects). Flutter, Xcode and Gradle builds are
   user commands (`flutter test`, `xcodebuild test ...`, `./gradlew test`).
10. **Release plan** per the checklist; write `mobile-plan.md`.

## Checklists

### Native or cross-platform
| Criterion | Native (SwiftUI / Jetpack Compose) | React Native + Expo | Flutter |
|---|---|---|---|
| Team skills | Swift and Kotlin, two codebases | JavaScript/TypeScript, React | Dart |
| Platform look and APIs | full, first on new OS features | broad via modules; native code when needed | broad via plugins; own rendering engine |
| Performance | best | good for most apps | good, consistent rendering |
| Code sharing | none (except Kotlin Multiplatform for logic) | high, also with a React web app | high |
| Fits | heavy device integration, top performance, AR | product apps, teams with web skills | custom UI, one design on both platforms |

### Platform conventions
- iOS: Apple Human Interface Guidelines — navigation bars, tab bars, swipe
  back, SF Symbols, safe areas, Dynamic Type.
- Android: Material Design 3 — top app bars, navigation bar or rail, system
  back gesture, edge-to-edge layout, dynamic colour where it fits.
- Do not port one platform's patterns to the other (no iOS-style back button
  on Android).

### Permissions and privacy
| Item | iOS | Android |
|---|---|---|
| Declare | `Info.plist` usage descriptions (`NSCameraUsageDescription`...) and a privacy manifest (`PrivacyInfo.xcprivacy`) | `AndroidManifest.xml` permissions; runtime request for dangerous ones |
| Store disclosure | App Store privacy details ("nutrition labels") | Google Play Data safety form |
| Location | "when in use" unless background is essential | foreground first; background asked separately |
| Tracking | App Tracking Transparency prompt before tracking across apps | advertising ID declaration |

### Accessibility
Touch targets ≥ 44×44 pt (iOS) and ≥ 48×48 dp (Android); system font scaling
honoured (Dynamic Type, `sp` units); VoiceOver and TalkBack labels on every
icon button; contrast per the design tokens; reduce-motion respected; no
information by colour alone.

### Performance
Cold start measured; lists virtualised (`FlatList`/`FlashList`, `LazyColumn`,
`ListView.builder`); images resized and cached; no heavy work on the UI
thread; background work through the platform scheduler (limits differ by OS);
app size watched.

### Release
| Step | iOS | Android |
|---|---|---|
| Identity | bundle id, Apple Developer account | application id, Google Play Console account |
| Signing | certificates and provisioning profiles (or Xcode automatic signing; EAS for Expo) | upload key and Play App Signing |
| Versions | `CFBundleShortVersionString` + build number | `versionName` + increasing `versionCode` |
| Beta | TestFlight | internal testing track |
| Review risks | missing privacy strings, login without a demo account, crashes, placeholder content, broken links | Data safety mismatch, missing permissions rationale, target SDK requirements |

## Deliverable
Code in the target folder, and `mobile-plan.md` in the shared work folder
(translate the headings into the user's language):

```markdown
# Mobile plan — <app>
## Summary
## Choice
| Criterion | Decision | Why |
## Screens and navigation
## Architecture
## Offline and sync
| Data | Cached | Sync | Conflict rule |
## Permissions and privacy
| Permission | Why | When asked | If denied | Store declaration |
## Push notifications
## Accessibility and performance
## Tests
| Level | Tool | Command | Result (as run / for the user) |
## Release steps (for the user)
## Decisions
## Next steps
```

## Pitfalls
- Asking for every permission at launch.
- No offline story: blank screens on the metro.
- Storing tokens in plain preferences or AsyncStorage instead of secure
  storage (iOS Keychain, Android Keystore-backed storage, or the framework's
  secure-storage module over them).
- One platform's UI patterns copied onto the other.
- Unvirtualised long lists; full-size images.
- Signing keys or `google-services.json` with real values committed.
- Privacy declarations that do not match what the app collects.
- Saying "tested on device" when only unit tests ran.
