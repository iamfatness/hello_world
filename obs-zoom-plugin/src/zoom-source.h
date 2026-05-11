#pragma once

#include <obs-module.h>
#include <string>
#include <memory>

#include "zoom-video-delegate.h"
#include "zoom-audio-delegate.h"

#define OBS_ZOOM_PLUGIN_VERSION "0.1.0"

// Register the Zoom participant source type with OBS.
void zoom_source_register();

// Internal source data — one instance per OBS source.
struct ZoomSource {
    obs_source_t *source   = nullptr;

    // Meeting / participant config
    std::string meeting_id;
    std::string passcode;
    uint32_t    participant_id = 0;  // 0 = auto (first active speaker)
    bool        auto_join      = false;

    // Audio channel mode — stored here so the property UI can read it back.
    AudioChannelMode audio_mode = AudioChannelMode::Mono;

    // Raw-data delegates (created after SDK authentication succeeds)
    std::unique_ptr<ZoomVideoDelegate> video_delegate;
    std::unique_ptr<ZoomAudioDelegate> audio_delegate;

    // Called when source properties are updated.
    void apply_settings(obs_data_t *settings);
};
