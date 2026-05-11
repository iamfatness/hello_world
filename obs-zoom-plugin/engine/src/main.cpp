// ZoomObsEngine — subprocess that hosts the Zoom Meeting SDK.
//
// The Zoom SDK cannot be loaded inside OBS's process safely (COM/UI thread
// conflicts, SDK-internal message pumping).  This process initialises the SDK,
// joins meetings, subscribes to participant video/audio streams, and forwards
// raw frames to the OBS plugin via named pipes (control) and shared memory
// (video frames).
//
// Build: see engine/CMakeLists.txt
// Launch: spawned by the OBS plugin at source creation time.

#include "../../src/engine-ipc.h"
#include "engine-video.h"
#include "engine-audio.h"

// Zoom SDK
// #include <zoom_sdk.h>
// #include <auth_service_interface.h>
// #include <meeting_service_interface.h>

#include <windows.h>
#include <string>
#include <thread>
#include <atomic>
#include <cstdio>

// Simple line-delimited JSON pipe helpers (replace with a real JSON lib).
static std::string read_line(HANDLE pipe)
{
    std::string line;
    char ch;
    DWORD read;
    while (ReadFile(pipe, &ch, 1, &read, nullptr) && read == 1) {
        if (ch == '\n') break;
        line += ch;
    }
    return line;
}

static void write_line(HANDLE pipe, const std::string &msg)
{
    std::string out = msg + "\n";
    DWORD written;
    WriteFile(pipe, out.c_str(), static_cast<DWORD>(out.size()), &written, nullptr);
}

int main()
{
    // Connect to plugin pipes
    HANDLE p2e = CreateNamedPipeA(PIPE_P2E, PIPE_ACCESS_INBOUND,
                                  PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                                  1, 4096, 4096, 0, nullptr);
    HANDLE e2p = CreateNamedPipeA(PIPE_E2P, PIPE_ACCESS_OUTBOUND,
                                  PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                                  1, 4096, 4096, 0, nullptr);

    ConnectNamedPipe(p2e, nullptr);
    ConnectNamedPipe(e2p, nullptr);

    write_line(e2p, R"({"cmd":"ready"})");

    std::atomic<bool> running{true};

    // Command loop
    while (running) {
        std::string line = read_line(p2e);
        if (line.empty()) continue;

        // Minimal command dispatch — replace with a real JSON parser.
        if (line.find(IPC_CMD_QUIT) != std::string::npos) {
            running = false;

        } else if (line.find(IPC_CMD_INIT) != std::string::npos) {
            // Parse sdk_key, sdk_secret, jwt_token from line and init SDK.
            // ZOOM_SDK_NAMESPACE::InitParam p; p.strWebDomain = "https://zoom.us";
            // ZOOM_SDK_NAMESPACE::InitSDK(p);
            // ... authenticate with JWT ...
            write_line(e2p, R"({"cmd":"auth_ok"})");

        } else if (line.find(IPC_CMD_JOIN) != std::string::npos) {
            // Parse meeting_id and passcode, call IMeetingService::Join().
            // After onMeetingStatusChanged(MEETING_STATUS_INMEETING):
            write_line(e2p, R"({"cmd":"joined","meeting_id":""})");

        } else if (line.find(IPC_CMD_LEAVE) != std::string::npos) {
            // IMeetingService::Leave(LEAVE_MEETING)
            write_line(e2p, R"({"cmd":"left"})");

        } else if (line.find(IPC_CMD_SUBSCRIBE) != std::string::npos) {
            // Parse source_uuid and participant_id.
            // EngineVideo::subscribe(participant_id, source_uuid, e2p);
            // EngineAudio::subscribe();

        } else if (line.find(IPC_CMD_UNSUBSCRIBE) != std::string::npos) {
            // EngineVideo::unsubscribe(source_uuid);
        }
    }

    // ZOOM_SDK_NAMESPACE::CleanUPSDK();
    CloseHandle(p2e);
    CloseHandle(e2p);
    return 0;
}
