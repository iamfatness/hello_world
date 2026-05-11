#pragma once

#include <windows.h>
#include <cstdint>
#include <string>

// Zoom SDK
// #include <rawdata/rawdata_audio_helper_interface.h>

#ifndef ZOOM_SDK_NAMESPACE
namespace ZOOM_SDK_NAMESPACE {
struct AudioRawData {
    virtual char     *GetBuffer()     = 0;
    virtual uint32_t  GetBufferLen()  = 0;
    virtual uint32_t  GetSampleRate() = 0;
    virtual uint32_t  GetChannelNum() = 0;
    virtual ~AudioRawData() = default;
};
struct IZoomSDKAudioRawDataDelegate {
    virtual void onMixedAudioRawDataReceived(AudioRawData *)                    = 0;
    virtual void onOneWayAudioRawDataReceived(AudioRawData *, uint32_t node_id) = 0;
    virtual ~IZoomSDKAudioRawDataDelegate() = default;
};
} // namespace ZOOM_SDK_NAMESPACE
#endif

// Shared-memory audio frame header.
// Region name: IPC_SHM_PREFIX + source_uuid + "_audio"
// Layout: [ShmAudioHeader][PCM bytes — 16-bit signed, 32 kHz, 1 ch]
#pragma pack(push, 1)
struct ShmAudioHeader {
    uint32_t sample_rate;
    uint16_t channels;     // 1 = mono, 2 = stereo (engine always writes 1)
    uint32_t byte_len;
};
#pragma pack(pop)

// ---------------------------------------------------------------------------
// EngineAudio — singleton audio delegate for the meeting.
//
// The Zoom SDK provides one mixed audio stream for the whole meeting (not
// per-participant).  The engine writes it into a single shared-memory region;
// each OBS source reads the same region and applies its own channel mode
// (mono/stereo duplication) in ZoomAudioDelegate on the plugin side.
// ---------------------------------------------------------------------------
class EngineAudio : public ZOOM_SDK_NAMESPACE::IZoomSDKAudioRawDataDelegate {
public:
    static EngineAudio &instance();

    void init(HANDLE e2p_pipe, const std::string &source_uuid);

    void onMixedAudioRawDataReceived(ZOOM_SDK_NAMESPACE::AudioRawData *data) override;
    void onOneWayAudioRawDataReceived(ZOOM_SDK_NAMESPACE::AudioRawData *data,
                                      uint32_t node_id) override;

private:
    EngineAudio() = default;

    void ensure_shm(uint32_t byte_len);

    HANDLE      m_e2p_pipe   = nullptr;
    std::string m_source_uuid;

    HANDLE  m_shm_handle = nullptr;
    void   *m_shm_ptr    = nullptr;
    size_t  m_shm_size   = 0;
};
