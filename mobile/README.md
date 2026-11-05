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

- [x] Both native projects generate and `cap sync` runs clean.
- [x] Permissions and portrait lock are set; the iOS "why we ask" wording is written.
- [ ] **Android has not been compiled or run.** This machine had no JDK or Android SDK.
- [ ] **iOS has never been built.** It needs a Mac and Xcode.
- [ ] **Camera, microphone and motion inside the app shell are untested.** This is
      the biggest technical risk: rep counting depends on all three, and they
      behave differently in an app webview than in Safari or Chrome. Test this
      on a real phone before anything else.

## Build on Android (Windows, Mac or Linux)

1. Install JDK 21 and Android Studio (it brings the SDK).
2. `cd mobile && npm install && npx cap sync android && npx cap open android`
3. Run on a real phone with USB debugging on. An emulator has no real camera.

## Build on iOS (needs a Mac)

1. Xcode and CocoaPods installed, an Apple Developer account ($99/year).
2. `cd mobile && npm install && npx cap sync ios && npx cap open ios`
3. Signing & Capabilities: pick the team. Run on a real iPhone.
4. If you do not own a Mac: a cloud Mac (MacinCloud, AWS EC2 Mac) or a CI
   service with macOS runners (GitHub Actions has them) can do the build.

## Before a store submission

- [ ] Real app icon and splash (1024x1024 icon, no transparency) from the OFFDAYS mark.
- [ ] Privacy policy lawyer-reviewed and its contact block filled in: `/app/privacy.html`.
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
