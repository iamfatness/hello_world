#pragma once

#include <obs-module.h>
#include <cstdint>
#include <atomic>

// Zoom SDK headers
// #include <rawdata/rawdata_renderer_interface.h>

// Mirrors the real SDK interface so this compiles without the SDK present.
// Remove this block and include the real header when linking the SDK.
#ifndef ZOOM_SDK_NAMESPACE
namespace ZOOM_SDK_NAMESPACE {
struct YUVRawDataI420 {
    virtual char     *GetYBuffer()      = 0;
    virtual char     *GetUBuffer()      = 0;
    virtual char     *GetVBuffer()      = 0;
    virtual uint32_t  GetStreamWidth()  = 0;
    virtual uint32_t  GetStreamHeight() = 0;
    virtual uint32_t  GetBufferLen()    = 0;
    virtual ~YUVRawDataI420() = default;
};
enum RawDataStatus { RawData_On, RawData_Off };
struct IZoomSDKRendererDelegate {
    virtual void onRawDataFrameReceived(YUVRawDataI420 *)  = 0;
    virtual void onRawDataStatusChanged(RawDataStatus)     = 0;
    virtual void onRendererBeDestroyed()                   = 0;
    virtual ~IZoomSDKRendererDelegate() = default;
};
} // namespace ZOOM_SDK_NAMESPACE
#endif

// ---------------------------------------------------------------------------
// ZoomVideoDelegate
//
// One instance per OBS source.  Registered with the engine via
// createRenderer() + subscribe(userId, RAW_DATA_TYPE_VIDEO).
//
// Received I420 frames are immediately pushed into the OBS source via
// obs_source_output_video().  The three YUV planes are handed to OBS
// directly without an extra copy wherever the SDK guarantees buffer
// lifetime for the duration of the callback.
// ---------------------------------------------------------------------------
class ZoomVideoDelegate : public ZOOM_SDK_NAMESPACE::IZoomSDKRendererDelegate {
public:
    explicit ZoomVideoDelegate(obs_source_t *source);
    ~ZoomVideoDelegate() override = default;

    // IZoomSDKRendererDelegate
    void onRawDataFrameReceived(ZOOM_SDK_NAMESPACE::YUVRawDataI420 *data) override;
    void onRawDataStatusChanged(ZOOM_SDK_NAMESPACE::RawDataStatus status) override;
    void onRendererBeDestroyed() override;

    bool is_active() const { return m_active.load(std::memory_order_relaxed); }

private:
    obs_source_t       *m_source;
    std::atomic<bool>   m_active{false};
};
