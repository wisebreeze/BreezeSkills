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

---

# Part B — BreezeAPI build & deploy

BreezeAPI ships as `libbreeze_api.so` (Dobby + QuickJS, 16KB-page aligned
for Android 15+). Your mod links against it and is loaded by the host app
that bundles `libbreeze_api.so` in its `jniLibs/`.

## 9. Build BreezeAPI itself

```bash
cd <BreezeAPI-dir>
ANDROID_NDK=<NDK> BREEZE_ABI=arm64-v8a ./build.sh
# output: build/arm64-v8a/out/lib/arm64-v8a/libbreeze_api.so
```

The build script sets `android-26`, `Release`, and 16KB page alignment.
Verify alignment:

```bash
readelf -l build/arm64-v8a/out/lib/arm64-v8a/libbreeze_api.so | grep LOAD | head -1
# expect: 0x4000 (16384) on Android 15+ targets
```

## 10. Link your mod against BreezeAPI

### Option A — IMPORTED shared library (recommended)

Copy `libbreeze_api.so` to your mod's `jniLibs/arm64-v8a/` and the
headers to an include dir:

```cmake
add_library(breeze_api SHARED IMPORTED)
set_target_properties(breeze_api PROPERTIES
    IMPORTED_LOCATION ${CMAKE_SOURCE_DIR}/../jniLibs/arm64-v8a/libbreeze_api.so
    INTERFACE_INCLUDE_DIRECTORIES ${BREEZE_API_INCLUDE_DIR}
)
add_library(mymod SHARED src/main.cpp)
target_link_libraries(mymod breeze_api log dl m)
```

### Option B — git submodule

```cmake
add_subdirectory(<path/to/BreezeAPI> breeze_api)
target_link_libraries(mymod breeze_api)
```

## 11. Mod entry for BreezeAPI

BreezeAPI does not use a registration macro. The host app loads
`libbreeze_api.so` and your mod `.so`, then calls a known entry point on
your mod (the exact name depends on the host; commonly `breeze_mod_init`):

```cpp
#include <breeze_api.h>

extern "C" __attribute__((visibility("default")))
void breeze_mod_init() {
    auto& api = breeze::BreezeAPI::Instance();
    api.Init();
    api.SetLogLevel(breeze::LogLevel::Info);
    // wait for libminecraftpe.so, then install hooks (see hook-techniques.md)
}
```

Export the entry with `-fvisibility=hidden` on the rest of the TU and
`__attribute__((visibility("default")))` on the entry symbol only.

## 12. CMakeLists.txt template (BreezeAPI mod)

```cmake
cmake_minimum_required(VERSION 3.22)
project(MyMod LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(mymod SHARED src/main.cpp)

target_include_directories(mymod PRIVATE
    ${BREEZE_API_INCLUDE_DIR}
)
target_link_libraries(mymod breeze_api log dl m)

# 16KB page alignment (Android 15+)
target_link_options(mymod PRIVATE
    -Wl,-z,max-page-size=16384
    -Wl,--gc-sections
)
if(NOT CMAKE_BUILD_TYPE STREQUAL "debug")
    target_compile_options(mymod PRIVATE -O2 -fvisibility=hidden)
    target_link_options(mymod PRIVATE -Wl,--strip-all -Wl,--exclude-libs,ALL)
endif()
```

## 13. Deploy

Push both `libbreeze_api.so` and `libmymod.so` to the host app's
`jniLibs/arm64-v8a/` (or let the host app bundle them). On device:

```bash
adb push libbreeze_api.so /data/app/<host-pkg>/lib/arm64/
adb push libmymod.so      /data/app/<host-pkg>/lib/arm64/
```

In practice the host app bundles the libs in its APK; you only push during
iterative development.

## 14. Verify with logcat

```bash
adb logcat -c
adb logcat | rg -i 'breeze\|mymod\|libminecraftpe'
```

Expected on a healthy load:

```
breeze: BreezeAPI init
breeze: hook installed: ServerTick (libminecraftpe.so + 0x1234560)
mymod: breeze_mod_init done
mymod: libminecraftpe.so base = 0x...
mymod: installed N hooks
```

If you see `symbol not found` for an unexported function, switch from
`HookBySymbol` to `HookByOffset` (the function is stripped).

## 15. BreezeAPI build issues

- `undefined reference to breeze::BreezeAPI::Instance()` → did not link
  `breeze_api` target, or include dir wrong.
- `dlopen failed: cannot locate symbol "breeze_mod_init"` → entry symbol
  hidden by `-fvisibility=hidden` without the explicit
  `__attribute__((visibility("default")))`.
- Crash on `Init()` → `libbreeze_api.so` not loaded before your mod, or
  architecture mismatch (must be `arm64-v8a`).
- `mprotect: Permission denied` → not aligning to the device page size
  (use 16384 on Android 15+).
- Hooks installed but never fire → offset is stale (game updated); re-derive
  from the current `.so`.

