# 0FFDAYS mobile shell

A Capacitor wrapper that puts the live web app (`https://app.0ffdays.com`) inside
a native iOS and Android app. No product code lives here: fix a bug in the web
app and every phone has it on the next launch, with no store review.

Directors and coaches keep using the website. Same server, same accounts.

## What is here

| Path | What |
|---|---|
| `capacitor.config.json` | App id `com.offdays.app`, loads the live site, may only navigate to `app.0ffdays.com` |
| `www/index.html` | What shows if the phone is offline at launch: "No connection, try again" |
| `android/` | Android Studio project |
| `ios/` | Xcode project (can be generated on Windows, **built only on a Mac**) |

Permissions are set honestly in `AndroidManifest.xml` and `Info.plist`: camera
and microphone (rep counting; nothing is recorded or sent), motion sensors, and
notifications.

## Status: what is and is not proven

Proven on an Android 15 emulator (hardware-accelerated, Windows host):

- [x] Both native projects generate and `cap sync` runs clean.
- [x] **Android compiles** (`./gradlew assembleDebug`, JDK 21, SDK 35) into a 4 MB APK
      with the right package, name, permissions and icon.
- [x] The app launches, loads the site and shows the landing page.
- [x] Signing in as an athlete from a link reaches the drill list.
- [x] **Camera and microphone work inside the app shell**: starting a drill gives a
      live video track (720x1280, playing) and the microphone is granted. This was
      the biggest risk and it is cleared **for the emulator's simulated camera**.
- [x] Permissions and portrait lock are set; the iOS "why we ask" wording is written.
- [x] Safe-area insets: the status bar no longer sits on top of the logo.

NOT proven:

- [ ] **A real phone.** An emulator's camera is a recorded scene. Rep counting
      accuracy, frame rate and heat on a real device are untested.
- [ ] **Rep counting itself.** The camera feeds the drill screen; nobody has thrown a
      ball at a wall in front of the app shell and checked the count.
- [ ] **Motion sensors:** the emulator reports none (`hasMotion` false). Untested.
- [ ] **iOS has never been built.** It needs a Mac and Xcode, and Safari's WebView
      behaves differently from Android's.
- [ ] **Release builds, signing, Play upload.** Only debug builds exist.
- [ ] **Push notifications.** Not built.

### The emulator needs a secure address

A WebView only hands out the camera and microphone on a **secure context**: HTTPS, or
`http://localhost`. Pointing the app at `http://10.0.2.2:8000` (the emulator's name for
your PC) gives `navigator.mediaDevices === undefined` and the drill screen shows a grey
box with no error. To test against a local server:

```
adb reverse tcp:8000 tcp:8000
```
and set `server.url` to `http://localhost:8000/app/index.html` with `cleartext: true` in
`capacitor.config.json`, then `npx cap sync`. **Put the config back to
`https://app.0ffdays.com` before committing**: the repo's config must point at production.

To look inside the running WebView: `adb forward tcp:9222
localabstract:webview_devtools_remote_<pid>` then
`node scripts/ui/webview-eval.mjs "<expression>"` (Playwright cannot attach to a WebView;
this talks the debugging protocol directly).

## Build on Android (Windows, Mac or Linux)

1. Install JDK 21 and the Android SDK (platform 35, build-tools 35.0.0), or Android Studio.
2. `cd mobile && npm install && npx cap sync android`
3. `cd android && ./gradlew assembleDebug` (set `JAVA_HOME` and `ANDROID_HOME`).
   The APK lands in `android/app/build/outputs/apk/debug/`.
4. Install it: `adb install -r app-debug.apk`, then test on a **real phone** with USB
   debugging on. The emulator proved the plumbing; it cannot prove rep counting.

## Build on iOS (needs a Mac)

1. Xcode and CocoaPods installed, an Apple Developer account ($99/year).
2. `cd mobile && npm install && npx cap sync ios && npx cap open ios`
3. Signing & Capabilities: pick the team. Run on a real iPhone.
4. If you do not own a Mac: a cloud Mac (MacinCloud, AWS EC2 Mac) or a CI
   service with macOS runners (GitHub Actions has them) can do the build.

## Before a store submission

- [x] App icon from the real mark: `python make_icons.py` (needs Pillow) writes the 1024 App Store icon, the 512 Play icon and every Android density into `assets/` and the native projects.
- [ ] Splash screen: still Capacitor's default.
- [ ] Privacy policy lawyer-reviewed: `/app/privacy.html`. Its contact block is filled in (K6 Labs LLC, Nashville, TN, mkallberg@k6-labs.com); add a street address if the lawyer asks.
- [ ] Apple "App Privacy" labels and Google "Data safety" form: answers are in `STORE_LISTING.md`.
- [ ] Children: both stores have extra rules for apps used by kids (Apple Kids
      Category and guideline 1.3, Google Play Families policy). `STORE_LISTING.md`
      says which apply and what each needs. Read it before choosing a category.
- [ ] A way for a reviewer to get in: a demo program with a parent already signed up.
- [ ] Apple guideline 4.2 ("not just a website"): the app uses the camera,
      microphone and motion sensors and works offline-aware. Push notifications
      would strengthen it further.
- [x] Account deletion inside the app (both stores require it): the parent portal
      has "Delete my account". Tell the reviewer where it is.
