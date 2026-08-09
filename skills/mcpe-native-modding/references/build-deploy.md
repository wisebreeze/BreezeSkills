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

---

# Part C — Rust build & deploy (mtbinloader2 patterns)

Rust mods compile to a `cdylib` (a `.so`) via `cargo` + an Android NDK
target. The reference is
[mtbinloader2](https://github.com/mcbegamerxx954/mtbinloader2).

## 16. Prerequisites

- Rust toolchain (latest stable).
- Android NDK r25+ installed; `ANDROID_NDK` env set, or the standalone
  toolchain in `PATH`.
- The Android target triple installed:
  ```bash
  rustup target add aarch64-linux-android
  # optional: armv7-linux-androideabi, x86_64-linux-android
  ```
- A linker from the NDK. Easiest: install `cargo-ndk`:
  ```bash
  cargo install cargo-ndk
  ```

## 17. Cargo.toml

```toml
[package]
name = "mymod"
version = "0.1.0"
edition = "2021"

[dependencies]
android_logger = { version = "0.15", default-features = false }
bhook = "0.1"
plt-rs = "0.4"
region = "3"
tinypatscan = "0.1"
ctor = "0.4"
libc = "0.2"
log = "0.4"
page_size = "0.6"
once_cell = "1"

[lib]
crate-type = ["cdylib"]

[profile.release]
panic = "abort"      # unwinding through foreign frames is UB
opt-level = "z"      # small binary
lto = true
codegen-units = 1
strip = true

[lints.clippy]
indexing_slicing = "deny"
unwrap_used = "deny"
```

`panic = "abort"` is mandatory: the `.so` is called from foreign (C++/JNI)
frames, and unwinding across them is undefined behavior.

## 18. build.rs (optional C/C++ interop)

If the mod needs a small C/C++ stub (e.g. a `std::string` bridge, like
mtbinloader2's `string.cpp`):

```rust
fn main() {
    cc::Build::new()
        .cpp(true)
        .file("src/string.cpp")
        .compile("stringstub");
}
```

Add `cc = "1"` to `[build-dependencies]`.

## 19. Build

With `cargo-ndk`:

```bash
cargo ndk -t arm64-v8a build --release
# output: target/aarch64-linux-android/release/libmymod.so
```

Without `cargo-ndk`, set the linker manually:

```bash
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$NDK/toolchains/llvm/prebuilt/<host>/bin/aarch64-linux-android24-clang"
cargo build --release --target aarch64-linux-android
```

Verify the result is an AArch64 ELF:

```bash
file target/aarch64-linux-android/release/libmymod.so
# expect: ELF 64-bit LSB shared object, ARM aarch64, stripped
```

## 20. 16KB page alignment (Android 15+)

Add to `.cargo/config.toml` or pass via `RUSTFLAGS`:

```toml
[target.aarch64-linux-android]
rustflags = ["-C", "link-arg=-Wl,-z,max-page-size=16384"]
```

Verify:

```bash
readelf -l libmymod.so | grep LOAD | head -1
# expect: 0x4000 (16384)
```

## 21. Deploy

Push the `.so` to the host app's lib dir (or bundle in the APK's
`jniLibs/arm64-v8a/`):

```bash
adb push libmymod.so /data/app/<host-pkg>/lib/arm64/
```

For LeviLauncher-style hosts that scan a `mods/` dir, drop the `.so`
there with a `manifest.json` (same manifest schema as the C++ preloader
path; the launcher does not care about the source language).

## 22. Verify with logcat

```bash
adb logcat -c
adb logcat | rg -i 'mymod\|libminecraftpe'
```

Expected:

```
mymod: loaded
mymod: libminecraftpe.so region: 0x... - 0x...
mymod: pattern matched at 0x...
mymod: hook installed
```

If you see `pattern not found`, the game version's pattern is missing
from your `PATTERNS` array — add it (see `version-porting.md` Part C).

## 23. Rust build issues

- `error: linker 'aarch64-linux-android-clang' not found` → NDK not in
  `PATH`, or target triple not added via `rustup target add`.
- `undefined reference to __cxa_...` → C++ interop stub not compiled by
  `build.rs`, or `cc` not in `[build-dependencies]`.
- `.so` loads but `#[ctor::ctor]` never runs → built as `staticlib`
  instead of `cdylib`; check `crate-type`.
- Crash on first hook → `panic = "abort"` missing, or hook installed at
  a non-executable address.
- Binary too large → enable `lto`, `opt-level = "z"`, `strip = true`,
  `codegen-units = 1`.
- `mprotect` fails → not aligning to `page_size::get()` (16384 on
  Android 15+).


