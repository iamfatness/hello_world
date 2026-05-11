# obs-zoom-plugin

An OBS Studio plugin that lets you capture a Zoom meeting as a source — stream or record Zoom calls without screen capture.

## Features

- **Zoom Meeting source** — appears in OBS as a native video/audio input
- **Auto-join** — joins a configured meeting ID automatically when the source becomes active
- **Audio control** — optionally mute incoming Zoom audio in OBS
- **JWT authentication** — uses the Zoom Meeting SDK with your app credentials

## Requirements

| Dependency | Version |
|---|---|
| OBS Studio | ≥ 30.0 |
| Zoom Meeting SDK | ≥ 6.x |
| CMake | ≥ 3.16 |
| C++ compiler | C++17 (MSVC 2022, Clang 14+, GCC 12+) |

## Building

### 1. Get the Zoom Meeting SDK

Download the [Zoom Meeting SDK](https://developers.zoom.us/docs/meeting-sdk/) for your platform and place it at `third_party/zoom-sdk/`.

Expected layout:
```
third_party/zoom-sdk/
  h/           # SDK headers
  lib/         # zoom_sdk_demo.lib / libmeetingsdk.dylib / .so
```

### 2. Configure and build

**Windows**
```bat
cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo `
      -DOBS_BUILD_DIR="C:\obs-studio\build64"
cmake --build build --config RelWithDebInfo
```

**macOS**
```bash
cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo \
      -DOBS_BUILD_DIR=/tmp/obs-studio/build
cmake --build build
```

**Linux**
```bash
cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build
```

### 3. Install

```bash
cmake --install build --prefix /path/to/obs-studio
```

Or copy manually:
- `build/obs-zoom-plugin.so` → `obs-plugins/64bit/`
- `data/` → `data/obs-plugins/obs-zoom-plugin/`

## Setup

1. Open OBS → **Tools → Zoom Plugin Settings**
2. Enter your **SDK Key** and **SDK Secret** (from [Zoom Marketplace](https://marketplace.zoom.us))
3. Paste a valid **JWT Token**
4. Add a new source → **Zoom Meeting**
5. Enter the **Meeting ID** and optional **Passcode**

## Architecture

```
plugin-main.cpp      — module entry point, OBS frontend event hook
zoom-source.cpp/h    — OBS source type (video + audio output)
zoom-auth.cpp/h      — Zoom SDK init and JWT authentication
zoom-meeting.cpp/h   — meeting join/leave and frame/audio callbacks
zoom-settings.cpp/h  — persistent settings via OBS global config
obs-utils.cpp/h      — helpers for pushing frames into OBS
```

## License

MIT
