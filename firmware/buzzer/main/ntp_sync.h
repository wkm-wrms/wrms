#pragma once

#include <stdbool.h>
#include <time.h>

/**
 * @brief Initialise the SNTP client and perform the first time sync.
 *
 * Blocks for up to 10 seconds waiting for a valid response from
 * pool.ntp.org. Sets the system timezone via the value stored in NVS.
 *
 * @return true if time was synchronised successfully; false on timeout.
 */
bool ntp_sync_init(void);

/**
 * @brief Trigger an immediate re-sync.
 *
 * Safe to call from any task. Blocks up to 5 s.
 *
 * @return true on success.
 */
bool ntp_sync_now(void);

/**
 * @brief Return true if the system clock has been synchronised at least once.
 */
bool ntp_sync_is_synced(void);

/**
 * @brief Return the current UTC time as a Unix timestamp (seconds since epoch).
 */
time_t ntp_sync_get_utc(void);
