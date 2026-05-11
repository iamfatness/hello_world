#pragma once

#include <string>

// Persisted per-user plugin settings (stored in OBS global config).
struct ZoomPluginSettings {
	std::string sdk_key;
	std::string sdk_secret;
	std::string jwt_token;

	// Load from OBS config (obs_frontend_get_global_config).
	static ZoomPluginSettings load();

	// Persist to OBS config.
	void save() const;
};
