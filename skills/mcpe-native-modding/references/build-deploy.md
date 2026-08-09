# Build, Package, Deploy, Verify

How to turn source into a deployed, verified MCPE native mod.

## 1. Project layout

```
<your-mod-dir>/
├── xmake.lua                  # or CMakeLists.txt
├── src/
│   ├── main.cpp               # PL_REGISTER_MOD entry
│   ├── core/
│   │   ├── Runtime.cpp        # dlopen probe, signature resolve, install flow
│   │   ├── GameHooks.cpp      # signature hooks + EGL hook (event sources)
│   │   └── Api.cpp            # third-party mod ABI (optional)
│   └── memory/
│       └── Hooks.hpp          # hooks::install/remove thin wrapper
├── include/
│   └── mymod/
│       ├── sdk/
│       │   ├── Memory.hpp      # patchMemory / field / virtualCall
│       │   ├── Functions.hpp   # signature address -> typed fn pointer
│       │   └── offsets/*.hpp  # member offsets + vtable slots
│       └── events/*.hpp       # typed event system
└── manifest.json              # mod metadata for the launcher
```

## 2. manifest.json

```json
{
  "name": "MyMod",
  "version": "1.0.0",
  "author": "your-name",
  "description": "A short description.",
  "entry": "libMyMod.so",
  "target_arch": "arm64-v8a",
  "target_game": "libminecraftpe.so"
}
```

The launcher validates `entry` exists and `target_arch` matches the device.

## 3. Build with NDK + CMake

```bash
mkdir build && cd build
cmake -DCMAKE_TOOLCHAIN_FILE=<NDK>/build/cmake/android.toolchain.cmake \
      -DANDROID_ABI=arm64-v8a \
      -DANDROID_PLATFORM=android-21 \
      -DCMAKE_BUILD_TYPE=Release \
      ..
cmake --build . --config Release -j
```

The output `libMyMod.so` must export `PLGetModRegistration`. Verify:

```bash
<NDK>/toolchains/llvm/prebuilt/<host>/bin/llvm-nm -D libMyMod.so | rg PLGetModRegistration
```

## 4. Build with xmake (alternative)

```bash
xmake f -p android -a arm64-v8a -m release
xmake
```

`xmake.lua` references the preloader dependency and sets arm64 flags.

## 5. Package into `.levipack`

```bash
python scripts/package_levipack.py \
    --manifest <your-mod-dir>/manifest.json \
    --so build/libMyMod.so \
    --resources <your-mod-dir>/res/ \
    --out MyMod-1.0.0.levipack
```

The script:

- Validates `manifest.json` schema.
- Bundles `manifest.json` + `libMyMod.so` + resources into a zip with the
  `.levipack` extension.
- Verifies the `.so` exports `PLGetModRegistration`.
- Verifies `target_arch` matches the `.so` machine type.

## 6. Deploy

Push the `.levipack` (or unpack into `mods/`) to the device:

```bash
adb push MyMod-1.0.0.levipack /sdcard/Android/data/<launcher-pkg>/files/mods/
```

Or unpack manually:

```bash
adb shell mkdir -p /sdcard/Android/data/<launcher-pkg>/files/mods/MyMod
adb push manifest.json /sdcard/Android/data/<launcher-pkg>/files/mods/MyMod/
adb push libMyMod.so   /sdcard/Android/data/<launcher-pkg>/files/mods/MyMod/
```

## 7. Verify with logcat

```bash
adb logcat -c
adb logcat | rg -i 'mymod\|preloader\|libminecraftpe'
```

Expected on a healthy load:

```
preloader: scanning mods/ ...
preloader: loading MyMod (libMyMod.so)
preloader: PLGetModRegistration ok
MyMod: load() begin
MyMod: GlossInit ok
MyMod: dlopen hook installed
MyMod: libminecraftpe.so loaded -> resolving signatures
MyMod: installed N hooks
```

If you see `version mismatch` or `AMBIGUOUS` warnings, stop and re-verify
signatures against this exact `.so`.

## 8. Common build issues

- `PLGetModRegistration` not exported → forgot `PL_REGISTER_MOD` in
  `main.cpp`, or the symbol is hidden by linker version script.
- `unsatisfied link` at load → built for the wrong ABI (must be
  `arm64-v8a`).
- Crash on first hook → `GlossInit(true)` not called, or signature is
  `AMBIGUOUS`/`MISSING`.
- Hooks silently do nothing → `GlossInit` called with `false` (linker-hook
  capability off).
