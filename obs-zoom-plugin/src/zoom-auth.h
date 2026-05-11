#pragma once

#include <string>
#include <functional>

enum class ZoomAuthState {
	Unauthenticated,
	Authenticating,
	Authenticated,
	Failed,
};

class ZoomAuth {
public:
	static ZoomAuth &instance();

	// Initialize the Zoom SDK with your app credentials.
	bool init(const std::string &sdk_key, const std::string &sdk_secret);

	// Authenticate using a JWT or OAuth token.
	bool authenticate(const std::string &jwt_token);

	ZoomAuthState state() const { return m_state; }

	// Called on plugin unload / OBS exit.
	void shutdown();

	using StateCallback = std::function<void(ZoomAuthState)>;
	void on_state_change(StateCallback cb) { m_callback = cb; }

private:
	ZoomAuth() = default;

	ZoomAuthState m_state    = ZoomAuthState::Unauthenticated;
	StateCallback m_callback;
	bool          m_sdk_init = false;
};
