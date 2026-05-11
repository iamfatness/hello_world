#pragma once

#include <obs-module.h>
#include <cstdint>
#include <vector>
#include <atomic>

// Zoom SDK headers
// #include <rawdata/rawdata_audio_helper_interface.h>

#ifndef ZOOM_SDK_NAMESPACE
namespace ZOOM_SDK_NAMESPACE {
struct AudioRawData {
    virtual char     *GetBuffer()    = 0;
    virtual uint32_t  GetBufferLen() = 0;  // bytes
    virtual uint32_t  GetSampleRate() = 0; // e.g. 32000
    virtual uint32_t  GetChannelNum() = 0; // SDK always delivers 1 (mono)
    virtual ~AudioRawData() = default;
};
struct IZoomSDKAudioRawDataDelegate {
    virtual void onMixedAudioRawDataReceived(AudioRawData *data)                     = 0;
    virtual void onOneWayAudioRawDataReceived(AudioRawData *data, uint32_t node_id)  = 0;
    virtual ~IZoomSDKAudioRawDataDelegate() = default;
};
} // namespace ZOOM_SDK_NAMESPACE
#endif

// Audio channel mode selectable per OBS source.
enum class AudioChannelMode {
    Mono   = 0,  // pass SDK mono buffer straight through → SPEAKERS_MONO
    Stereo = 1,  // duplicate mono to L+R            → SPEAKERS_STEREO
};

// ---------------------------------------------------------------------------
// ZoomAudioDelegate
//
// One instance per OBS source.  Subscribes to the mixed (all-participants)
// audio stream.  Per-participant streams (onOneWayAudioRawDataReceived) are
// available if needed but not wired to OBS here — extend as required.
//
// The Zoom SDK always delivers 16-bit signed PCM at 32 kHz, mono.
// When the source is configured for stereo the mono samples are duplicated
// to both channels before being handed to OBS (L = R = mono sample).
// ---------------------------------------------------------------------------
class ZoomAudioDelegate : public ZOOM_SDK_NAMESPACE::IZoomSDKAudioRawDataDelegate {
public:
    explicit ZoomAudioDelegate(obs_source_t *source,
                               AudioChannelMode mode = AudioChannelMode::Mono);
    ~ZoomAudioDelegate() override = default;

    // Change mode at runtime (e.g. when the user edits source properties).
    void set_channel_mode(AudioChannelMode mode);
    AudioChannelMode channel_mode() const;

    // IZoomSDKAudioRawDataDelegate
    void onMixedAudioRawDataReceived(ZOOM_SDK_NAMESPACE::AudioRawData *data) override;
    void onOneWayAudioRawDataReceived(ZOOM_SDK_NAMESPACE::AudioRawData *data,
                                      uint32_t node_id) override;

private:
    void push_mono(ZOOM_SDK_NAMESPACE::AudioRawData *data);
    void push_stereo(ZOOM_SDK_NAMESPACE::AudioRawData *data);

    obs_source_t            *m_source;
    std::atomic<int>         m_mode;          // AudioChannelMode as int
    std::vector<int16_t>     m_stereo_buf;    // reused across callbacks
};
