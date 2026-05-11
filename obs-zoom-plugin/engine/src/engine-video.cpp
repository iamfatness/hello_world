#include "engine-video.h"
#include "../../src/engine-ipc.h"

#include <cstring>
#include <string>

// ---------------------------------------------------------------------------
// ParticipantSubscription
// ---------------------------------------------------------------------------

ParticipantSubscription::ParticipantSubscription(
    uint32_t participant_id,
    const std::string &source_uuid,
    HANDLE e2p_pipe)
    : m_participant_id(participant_id)
    , m_source_uuid(source_uuid)
    , m_e2p_pipe(e2p_pipe)
{
    // ZOOM_SDK_NAMESPACE::IZoomSDKRenderer *renderer = nullptr;
    // createRenderer(&renderer, this);
    // renderer->subscribe(participant_id, RAW_DATA_TYPE_VIDEO);
}

ParticipantSubscription::~ParticipantSubscription()
{
    if (m_shm_ptr)    UnmapViewOfFile(m_shm_ptr);
    if (m_shm_handle) CloseHandle(m_shm_handle);
}

void ParticipantSubscription::ensure_shm(uint32_t y_len)
{
    // y (full) + u (quarter) + v (quarter) + header
    const size_t frame_bytes = y_len + y_len / 4 + y_len / 4;
    const size_t total       = sizeof(ShmFrameHeader) + frame_bytes;

    if (m_shm_handle && m_shm_size >= total)
        return; // already large enough

    if (m_shm_ptr)    { UnmapViewOfFile(m_shm_ptr); m_shm_ptr = nullptr; }
    if (m_shm_handle) { CloseHandle(m_shm_handle);  m_shm_handle = nullptr; }

    const std::string region_name = IPC_SHM_PREFIX + m_source_uuid;
    m_shm_handle = CreateFileMappingA(INVALID_HANDLE_VALUE, nullptr,
                                      PAGE_READWRITE, 0,
                                      static_cast<DWORD>(total),
                                      region_name.c_str());
    m_shm_ptr  = MapViewOfFile(m_shm_handle, FILE_MAP_WRITE, 0, 0, total);
    m_shm_size = total;
}

void ParticipantSubscription::onRawDataFrameReceived(
    ZOOM_SDK_NAMESPACE::YUVRawDataI420 *data)
{
    if (!data) return;

    const uint32_t w     = data->GetStreamWidth();
    const uint32_t h     = data->GetStreamHeight();
    const uint32_t y_len = w * h;

    ensure_shm(y_len);
    if (!m_shm_ptr) return;

    auto *hdr    = static_cast<ShmFrameHeader *>(m_shm_ptr);
    auto *pixels = static_cast<char *>(m_shm_ptr) + sizeof(ShmFrameHeader);

    hdr->width  = w;
    hdr->height = h;
    hdr->y_len  = y_len;

    // Copy I420 planes sequentially: Y, U, V
    std::memcpy(pixels,                      data->GetYBuffer(), y_len);
    std::memcpy(pixels + y_len,              data->GetUBuffer(), y_len / 4);
    std::memcpy(pixels + y_len + y_len / 4,  data->GetVBuffer(), y_len / 4);

    // Notify the plugin that a new frame is ready.
    const std::string msg =
        R"({"cmd":"frame","source_uuid":")" + m_source_uuid +
        R"(","w":)" + std::to_string(w) +
        R"(,"h":)" + std::to_string(h) + "}";
    const std::string line = msg + "\n";
    DWORD written;
    WriteFile(m_e2p_pipe, line.c_str(),
              static_cast<DWORD>(line.size()), &written, nullptr);
}

void ParticipantSubscription::onRawDataStatusChanged(
    ZOOM_SDK_NAMESPACE::RawDataStatus /*status*/) {}

void ParticipantSubscription::onRendererBeDestroyed() {}

// ---------------------------------------------------------------------------
// EngineVideo
// ---------------------------------------------------------------------------

void EngineVideo::subscribe(uint32_t participant_id,
                            const std::string &source_uuid,
                            HANDLE e2p_pipe)
{
    m_subs[source_uuid] = std::make_unique<ParticipantSubscription>(
        participant_id, source_uuid, e2p_pipe);
}

void EngineVideo::unsubscribe(const std::string &source_uuid)
{
    m_subs.erase(source_uuid);
}
