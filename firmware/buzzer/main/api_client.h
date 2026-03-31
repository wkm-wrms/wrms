#pragma once

#include <stdbool.h>
#include <time.h>

/* Maximum number of alarms that can be buffered from a single API response. */
#define API_MAX_ALARMS 20

/* Maximum alarm ID string length (including null terminator). */
#define API_ALARM_ID_LEN 48

/* Maximum alarm type string length (including null terminator). */
#define API_ALARM_TYPE_LEN 24

typedef struct {
    char     id[API_ALARM_ID_LEN];
    char     type[API_ALARM_TYPE_LEN];
    time_t   fire_at;              /* UTC Unix timestamp */
} api_alarm_t;

typedef enum {
    API_PHASE_IDLE = 0,
    API_PHASE_PREP,
    API_PHASE_FLIGHT,
    API_PHASE_UNKNOWN,
} api_phase_t;

typedef struct {
    bool         ok;               /* false if request or parse failed */
    api_phase_t  phase;
    int          poll_interval_sec;
    time_t       server_time;      /* UTC Unix timestamp from server */
    api_alarm_t  alarms[API_MAX_ALARMS];
    int          alarm_count;
} api_response_t;

/**
 * @brief Perform a single GET /api/buzzer request and parse the JSON response.
 *
 * The caller supplies the full URL (e.g. "http://192.168.1.10:8000/api/buzzer").
 * The response is written into *out*. Returns false and sets out->ok = false on
 * network or parse failure.
 *
 * @param url    Null-terminated URL string.
 * @param[out] out  Caller-allocated result structure.
 * @return       true on success.
 */
bool api_client_fetch(const char *url, api_response_t *out);
