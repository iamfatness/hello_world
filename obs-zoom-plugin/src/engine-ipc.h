#pragma once

// ---------------------------------------------------------------------------
// Plugin ↔ Engine IPC protocol
//
// Two named pipes carry line-delimited JSON in each direction:
//
//   Plugin → Engine   \\.\pipe\ZoomObsPlugin_P2E
//   Engine → Plugin   \\.\pipe\ZoomObsPlugin_E2P
//
// Video frames travel via a named file-mapping (shared memory) keyed on
// source UUID so multiple sources can receive independent participant streams
// without data copies through the pipe.
//
// Message format  { "cmd": "<COMMAND>", ...fields }
// ---------------------------------------------------------------------------

// Commands: Plugin → Engine
#define IPC_CMD_INIT        "init"         // { sdk_key, sdk_secret, jwt_token }
#define IPC_CMD_JOIN        "join"         // { meeting_id, passcode }
#define IPC_CMD_LEAVE       "leave"        // {}
#define IPC_CMD_SUBSCRIBE   "subscribe"    // { source_uuid, participant_id }
#define IPC_CMD_UNSUBSCRIBE "unsubscribe"  // { source_uuid }
#define IPC_CMD_QUIT        "quit"         // {}

// Commands: Engine → Plugin
#define IPC_EVT_READY       "ready"        // engine started, SDK init ok
#define IPC_EVT_AUTH_OK     "auth_ok"      // JWT auth succeeded
#define IPC_EVT_AUTH_FAIL   "auth_fail"    // { error }
#define IPC_EVT_JOINED      "joined"       // { meeting_id }
#define IPC_EVT_LEFT        "left"         // {}
#define IPC_EVT_FRAME       "frame"        // { source_uuid, w, h } — data in SHM
#define IPC_EVT_AUDIO       "audio"        // { source_uuid } — audio data in SHM
#define IPC_EVT_ERROR       "error"        // { message }

// Shared-memory region name for a source's video frames.
// Format:  "ZoomObsPlugin_<source_uuid>"
// Layout:  [uint32_t width][uint32_t height][uint32_t y_len]
//          [Y bytes][U bytes][V bytes]
//          (U/V each = y_len/4 bytes for I420)
#define IPC_SHM_PREFIX "ZoomObsPlugin_"

static constexpr const char *PIPE_P2E = "\\\\.\\pipe\\ZoomObsPlugin_P2E";
static constexpr const char *PIPE_E2P = "\\\\.\\pipe\\ZoomObsPlugin_E2P";
