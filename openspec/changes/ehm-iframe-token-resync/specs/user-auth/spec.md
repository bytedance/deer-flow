## ADDED Requirements

### Requirement: 宿主刷新 EHM token 后 DeerFlow iframe 可无刷新接收新 token

When DeerFlow runs inside an EHM-hosted iframe, the frontend SHALL accept a host-driven token refresh message and update its EHM authentication context without reloading the page.

#### Scenario: Host pushes a newer EHM token

- **GIVEN** DeerFlow is already loaded inside the EHM iframe
- **AND** the page currently holds an older `ehm_token`
- **WHEN** the host sends a valid `AI_TOKEN_REFRESH` message carrying a newer token
- **THEN** DeerFlow SHALL update its local `ehm_token`
- **AND** SHALL keep the current page and thread state intact
- **AND** SHALL NOT reload the iframe page

### Requirement: New host token triggers DeerFlow session re-authentication

After DeerFlow accepts a newer host-provided EHM token, the frontend SHALL proactively rebuild its internal session by calling `/api/v1/auth/ins-base/authenticate`.

#### Scenario: Accepting a new token rebuilds the session

- **GIVEN** DeerFlow accepted a refreshed host `ehm_token`
- **WHEN** the frontend processes that token refresh
- **THEN** the frontend SHALL call `/api/v1/auth/ins-base/authenticate` with the new token
- **AND** successful authentication SHALL refresh DeerFlow's internal session cookie

### Requirement: Older host token refresh messages must not overwrite newer state

DeerFlow SHALL ignore stale host token refresh messages when it has already accepted a newer refresh payload.

#### Scenario: Out-of-order host refresh messages

- **GIVEN** DeerFlow already accepted a token refresh message with `issuedAt=200`
- **WHEN** it later receives another `AI_TOKEN_REFRESH` message with `issuedAt=100`
- **THEN** DeerFlow SHALL ignore the older message
- **AND** SHALL keep the newer token and session state unchanged

### Requirement: 401 时 DeerFlow 应先向宿主请求最新可用 token

When DeerFlow is running inside an EHM-hosted iframe and its current EHM token is no longer usable, the frontend SHALL request a fresh host token before falling back to the final login redirect path.

#### Scenario: iframe first hits 401 while host has not refreshed yet

- **GIVEN** the user stayed only on the AI workbench page
- **AND** the outer EHM host has not yet made another request that would trigger its own refresh
- **AND** DeerFlow encounters `401` with an expired EHM token
- **WHEN** DeerFlow starts its host recovery flow
- **THEN** DeerFlow SHALL first send `AI_REQUEST_USER` to the host
- **AND** SHALL wait for the host to provide a newer `AI_TOKEN_REFRESH` payload before falling back to the final login redirect path

### Requirement: DeerFlow login page can also recover from host token refresh

The host token bridge SHALL remain available on DeerFlow auth pages so that a page already redirected to `/login` can still recover when the host later sends a fresh EHM token.

#### Scenario: host refreshes after iframe already dropped to login

- **GIVEN** DeerFlow already redirected the iframe to `/login`
- **WHEN** the host later refreshes its token and sends `AI_TOKEN_REFRESH`
- **THEN** the login page SHALL accept the message
- **AND** SHALL rebuild DeerFlow session state using the new token

### Requirement: DeerFlow login page shall actively retry host token recovery

When DeerFlow has already redirected the iframe to `/login`, the login page SHALL actively request a fresh host token instead of relying only on the earlier 401-time request.

#### Scenario: login page re-requests host token after previous timeout

- **GIVEN** DeerFlow already redirected to `/login` after a 401
- **AND** the earlier host token request timed out before the host finished refresh
- **WHEN** the login page finishes mounting inside the iframe
- **THEN** it SHALL send another `AI_REQUEST_USER` to the host
- **AND** SHALL use the returned `AI_TOKEN_REFRESH` payload to overwrite the stale local `ehm_token`

### Requirement: DeerFlow shall wait long enough for host refresh before failing over

When DeerFlow asks the host for a fresh EHM token, it SHALL wait long enough to cover a normal host-side refresh round trip before treating the request as failed.

#### Scenario: host refresh completes after more than 1.5 seconds

- **GIVEN** the host needs more than 1.5 seconds to finish a refresh and return a new token
- **WHEN** DeerFlow is waiting for `AI_TOKEN_REFRESH`
- **THEN** it SHALL keep waiting within the configured recovery timeout window
- **AND** SHALL NOT fail over to the login redirect solely because of the earlier 1.5-second limit

### Requirement: DeerFlow shall gate new business requests while session recovery is running

When DeerFlow has already started EHM session recovery, new business API requests SHALL wait for that recovery to finish before they are sent, so the UI does not surface a cascade of avoidable 401 responses.

#### Scenario: concurrent requests arrive during session recovery

- **GIVEN** one DeerFlow API request has already received `401`
- **AND** DeerFlow has started EHM session recovery
- **WHEN** additional DeerFlow business requests are triggered before recovery completes
- **THEN** those requests SHALL wait for the in-flight recovery promise
- **AND** SHALL only be sent after recovery completes or fails
- **AND** SHALL NOT independently hit the gateway with the stale pre-recovery session by default

### Requirement: DeerFlow shall cancel stale delayed login redirects after recovery succeeds

When DeerFlow has already scheduled a delayed redirect to `/login`, that redirect SHALL be canceled if session recovery later succeeds before the timer fires.

#### Scenario: delayed login redirect becomes stale after recovery

- **GIVEN** one request has already scheduled a delayed redirect to `/login`
- **AND** DeerFlow later restores session successfully through host recovery or refresh
- **WHEN** the earlier redirect timer is about to fire
- **THEN** DeerFlow SHALL cancel or suppress that stale redirect
- **AND** SHALL keep the user on the recovered workspace page

### Requirement: Bridge-driven session recovery shall notify the global auth recovery state

When DeerFlow restores its session from an `AI_TOKEN_REFRESH` message outside the original failed request path, that success SHALL still update the global auth recovery state used by the fetch layer.

#### Scenario: host bridge authenticates successfully before stale redirect fires

- **GIVEN** a prior request has already scheduled a delayed redirect to `/login`
- **AND** the host bridge later receives `AI_TOKEN_REFRESH`
- **AND** the bridge successfully calls `/api/v1/auth/ins-base/authenticate`
- **WHEN** that bridge-side recovery succeeds
- **THEN** DeerFlow SHALL publish a global recovery success signal
- **AND** the fetch layer SHALL treat that signal as sufficient to cancel the stale delayed redirect

### Requirement: The first iframe 401 shall only trigger recovery, not an immediate login redirect

When DeerFlow is running with an `ehm_token` inside the host iframe, the first business request that hits `401` SHALL start recovery without immediately treating that single failure as a final signal to redirect the whole iframe to `/login`.

#### Scenario: first 401 happens before the refreshed host token has finished rebuilding session

- **GIVEN** DeerFlow is running inside the EHM iframe with an `ehm_token`
- **AND** the first business request returns `401`
- **WHEN** DeerFlow begins its EHM recovery flow for that request
- **THEN** that request SHALL only trigger recovery and surface its own `401` result
- **AND** SHALL NOT immediately schedule a whole-page redirect to `/login`
- **AND** a later request may still trigger the final login redirect if recovery remains unsuccessful

### Requirement: Shared auth error helpers shall honor the iframe recovery window

When a business component catches a `401` and uses the shared auth error helper, that helper SHALL suppress any extra login redirect while the iframe EHM recovery window is still active.

#### Scenario: business error handling sees 401 during the recovery window

- **GIVEN** DeerFlow has already entered an EHM recovery window for an iframe session
- **WHEN** a component resolves the same `401` through the shared auth error helper
- **THEN** the helper SHALL NOT schedule an additional redirect to `/login`
- **AND** SHALL allow the global recovery flow to decide whether the session ultimately recovers or fails
