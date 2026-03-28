# Admin Authentication — Design Document

## Status: Pending implementation

---

## Scope

The admin panel (`session.html`, `groups.html`) must be protected by authentication.
The public dashboard (`dashboard.html`) must remain fully accessible without any login.

---

## Public vs Protected Endpoints

### Always public (no auth required)

| Endpoint | Reason |
|---|---|
| `GET /api/heat` | Called by the public dashboard — must work without login |
| `GET /api/pilot/` | Read-only pilot list; pilot names are not sensitive |
| `GET /api/pilot/search/{query}` | Read-only search; used by admin panel but not sensitive |
| `GET /api/pilot/{id}` | Read-only lookup |
| `POST /api/admin/login` | Login endpoint must be public by definition |
| `POST /api/admin/register` | Public **only** when no admins exist in DB (first-time setup); requires auth otherwise |

### Requires authentication

Everything else:
- All `POST /api/session/*`
- All `POST /api/groups/*`
- `POST /api/pilot/` (creating pilots)
- All `POST /api/admin/*` except login and first-time register

---

## URL Structure

**Option A (chosen):** keep existing route paths, add auth as a FastAPI `Depends()` on individual endpoints.

- No frontend URL changes needed.
- Auth dependency (`require_admin`) is injected per-router or per-endpoint.
- Clearly visible in router code which endpoints are protected.

Rejected alternative: split into `/api/admin/*` prefix — would require rewriting all
`fetch()` calls in HTML and is more work for no functional gain at this stage.

---

## Authentication Mechanism

**Session cookie (HttpOnly):**
- Login → generate a random token → store `{token: username}` in an in-memory dict → set cookie
- Every protected request → read cookie → validate token → proceed or return 401 JSON error
- Logout → delete token from dict → clear cookie

**Why DB-backed sessions (not in-memory):**
- Shared hosting kills worker processes frequently (after inactivity, memory limits, etc.)
- In-memory sessions would be wiped on every process restart, logging out the MC mid-event
- Sessions stored in DB survive process restarts transparently

**Cookie settings:**
- `HttpOnly`: JS cannot read it (XSS protection)
- `SameSite=Strict`: CSRF protection
- No `Secure` flag required (shared hosting, no HTTPS guaranteed)

---

## Admin Management Endpoints

All require authentication except where noted.

| Endpoint | Auth | Description |
|---|---|---|
| `POST /api/admin/login` | Public | Validates credentials, sets session cookie |
| `POST /api/admin/logout` | Required | Clears session cookie and invalidates token |
| `GET /api/admin/me` | Required | Returns current admin username; used by frontend on load |
| `POST /api/admin/register` | Public if no admins exist; auth otherwise | Creates a new admin account |
| `POST /api/admin/set_password` | Required | Changes password for any admin (including others) |
| `GET /api/admin/list` | Required | Lists all admins (username + created_at, no password hash) |
| `DELETE /api/admin/remove` | Required | Removes an admin; cannot remove own account |

---

## First-Time Setup Flow

1. Fresh install: `user` table in DB is empty.
2. MC navigates to `/admin`.
3. Frontend calls `GET /api/admin/me` → gets `{"status": "error", "first_setup": true}`.
4. Frontend shows registration form instead of login form.
5. MC creates first admin account via `POST /api/admin/register`.
6. Subsequent visits show the login form.

---

## Password Recovery

No email-based recovery. Two recovery paths:

**Path 1 — Admin resets another admin's password** (normal operation):
Any authenticated admin can call `POST /api/admin/set_password` for any username,
including other admins. No confirmation required beyond being logged in.

**Path 2 — All admins locked out** (emergency):
Run the CLI recovery script directly on the server (requires shell access):

```bash
python manage_admins.py reset --username <name> --password <new_password>
```

This script connects directly to `data/race_system.db` and updates the password hash.
No running server required.

The script must be implemented alongside the auth feature.

---

## No Permission Levels

All admins have identical permissions — full access to all protected endpoints.
Role-based access control is explicitly out of scope for this version.

---

## Frontend Behaviour

- On load of any admin page: call `GET /api/admin/me`.
  - If `status: "ok"` → proceed normally.
  - If `status: "error"` → redirect to login page (or show login modal).
- All protected API calls already use try/catch + `data.status` checks (done 2026-03-28).
  A 401-equivalent error response (`{"status": "error", "message": "Unauthorized"}`)
  will be handled uniformly by existing error handling — show alert and optionally redirect.

---

## Open Decisions (to confirm before implementation)

1. **Pilot write endpoint auth**: `POST /api/pilot/` (creating pilots) — protected (decided).

2. **Session persistence**: DB-backed sessions (decided — shared hosting kills processes too frequently for in-memory to be viable).

3. **Login UI**: modal overlay on `session.html` (decided).

---

*Created: 2026-03-28*
