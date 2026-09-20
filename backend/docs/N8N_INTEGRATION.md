# N8N Integration Guide: DeerFlow + n8n

## 1. Overview

### 1.1 Purpose

This document is a **practical integration guide**. It focuses on the last-mile problem: "After creating a PAT, how do you actually use DeerFlow in n8n?"

The official documentation already covers PAT generation, permission models, and API endpoints, but it does not cover:

- How to configure the n8n HTTP Request node;
- How to parse SSE streaming responses;
- Cross-system networking in Windows + WSL2 scenarios;
- How to dynamically inject Apify scraped data into DeerFlow;
- Common error codes and troubleshooting paths.

This document assumes you already understand the basic concept of a Personal Access Token (PAT) and have successfully created a token starting with `dfp_`. If you are not yet familiar with the PAT creation process or underlying mechanisms, please read:

- [Personal Access Tokens section in the API Reference](API.md#personal-access-tokens)
- [Database Configuration Guide](CONFIGURATION.md#database-backend)

### 1.2 Core Value

DeerFlow is a super agent with deep research capabilities that can autonomously search, analyze data, and generate reports. n8n is a powerful workflow automation engine that excels at connecting various business systems. Combining the two can build true end-to-end e-commerce AI tools:

- **n8n handles process orchestration**: scheduled triggers, receiving Webhooks, calling external systems, pushing notifications.
- **DeerFlow handles deep research**: market trend analysis, competitor price monitoring, product selection insights, intelligent customer service reply generation.

For example: automatically analyze competitor prices at 9 AM every day and push the report to a Feishu group; or when a customer submits a complex after-sales issue, DeerFlow generates a deep reply suggestion.

### 1.3 Target Audience

This document is suitable for:

- **Automation engineers**: familiar with basic n8n operations and want to integrate DeerFlow's research capabilities into existing workflows.
- **E-commerce operations developers**: want to use AI to automate repetitive tasks such as market analysis, competitor monitoring, and product research.
- **Technical product managers**: need to evaluate the feasibility and implementation path of DeerFlow + n8n integration.

### 1.4 Prerequisites

Before continuing, please ensure you have:

- A working DeerFlow instance, and the Gateway service is accessible at `http://localhost:2026`.
- A successfully created PAT starting with `dfp_`, with `runs:create` and `runs:read` permissions.
- A working n8n environment (local installation, Docker deployment, or Docker container in WSL2).
- Basic knowledge of HTTP requests and JSON format.

If you have not completed any of the above, please refer to the official documentation first.

---

## 2. Prerequisites

Before starting the integration, please confirm the following conditions are met. This section provides specific verification methods to help you quickly determine whether your environment is ready.

### 2.1 Database Backend

PAT functionality depends on a persistent database backend. DeerFlow uses SQLite by default and usually requires no extra configuration.

Quick check: Open `config.yaml` and confirm `database.backend` is `sqlite` or `postgres`. If it is `memory`, please refer to the official documentation to switch it first.

Related documentation: [Database Backend Configuration](CONFIGURATION.md#database-backend)

### 2.2 DeerFlow Service Status

Ensure the Gateway service is running and the API is accessible.

Verification method: Open `http://localhost:2026` in a browser. If you can see the DeerFlow interface, it is working.

For command-line verification, you can run:

```bash
curl http://localhost:8001/health
```

Additionally, verify the Nginx proxy chain:

```bash
curl http://localhost:2026/api/models
```

If it returns a valid JSON response, the complete proxy chain from Nginx to Gateway is working.

### 2.3 Created PAT

You need a PAT starting with `dfp_`. Please refer to the official API documentation for creation.

Required scopes for n8n integration: at least select `runs:create` and `runs:read`. This is the minimum permission requirement for n8n to call the `/runs/stream` endpoint.

Related documentation: [API Reference — Personal Access Tokens](API.md#personal-access-tokens)

### 2.4 Automating PAT Creation (Optional)

If you prefer to create a PAT via a script rather than manually extracting data from developer tools, you can use the following Python script. It automatically logs in, extracts the CSRF Token, and calls `POST /api/v1/auth/pats` to create a token.

#### 2.4.1 Install Dependencies

```bash
pip install requests
```

#### 2.4.2 Script Code (Copy and Run)

Save the following code as `create_deerflow_pat.py`:

```python
import argparse
import sys

import requests


def create_pat(base_url, username, password, name, scopes, expires_days=None):
    s = requests.Session()

    # 1. Login: the API expects username, not email
    resp = s.post(
        f"{base_url}/api/v1/auth/login/local",
        data={"username": username, "password": password},
    )
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    # 2. Extract CSRF Token
    csrf = s.cookies.get("csrf_token")
    headers = {"X-CSRF-Token": csrf} if csrf else {}

    # 3. Create PAT
    body = {"name": name, "scopes": scopes}
    if expires_days:
        body["expires_in_days"] = expires_days

    resp = s.post(f"{base_url}/api/v1/auth/pats", json=body, headers=headers)
    if resp.status_code == 201:
        data = resp.json()
        print(
            f"✅ Token created successfully!\n"
            f"Token name: {data.get('name')}\n"
            f"Token: {data.get('token')}"
        )
        print("⚠️ Please save it immediately; this token is shown only once.")
    else:
        print(f"Creation failed: {resp.status_code} {resp.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:2026")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="n8n-integration")
    parser.add_argument("--scopes", nargs="+", default=["runs:create", "runs:read"])
    parser.add_argument("--expires-days", type=int, default=90)
    args = parser.parse_args()

    create_pat(
        args.base_url,
        args.username,
        args.password,
        args.name,
        args.scopes,
        args.expires_days,
    )
```

#### 2.4.3 How to Run

```bash
python create_deerflow_pat.py \
  --username your_email@example.com \
  --password 'your_password'
```

> **Note for Windows PowerShell users**: PowerShell does not support `\` as a line continuation character. Please use the backtick `` ` `` or write the command on a single line.

#### 2.4.4 Common Errors


| Error | Cause | Solution |
| ----- | ----- | -------- |
| `422 Validation Error`, missing `username` or `password` | The login endpoint expects form field `username`, not `email`; the body should use `application/x-www-form-urlencoded` | Use `data={"username": ..., "password": ...}` and change the CLI argument to `--username` |
| PowerShell reports `Unary operator "--" is missing an expression` | PowerShell does not support `\` as a line continuation character | Use the backtick `` ` `` or a single-line command |
| `401 Unauthorized` | Incorrect account or password | Confirm the DeerFlow login email and password |
| `503 Service Unavailable` | Database backend is `memory` | Refer to the [Database Configuration Guide](CONFIGURATION.md#database-backend) to switch to SQLite or PostgreSQL |

### 2.5 n8n Environment

Confirm n8n is installed and accessible. n8n can run in any of the following environments:

- **Local installation**: Run directly on Windows/macOS/Linux.
- **Docker container**: Including Docker containers running in WSL2.

#### Verification Method 1: Browser Access

Open `http://localhost:5678` in a browser. If you can see the n8n workflow editor, the n8n service is running normally.

#### Verification Method 2: Docker Container Status Check (WSL2 Scenario)

If you run n8n via Docker Compose in WSL2, open an Ubuntu terminal and run:

```bash
cd /path/to/your/n8n-docker
docker compose ps
```

> Replace `/path/to/your/n8n-docker` with the actual directory containing your `docker-compose.yml`. For example, in WSL2, if the project is on the Windows D drive, the path might look like `/mnt/d/your-folder/n8n-docker`. If the output shows the `n8n` container status as `Running`, the container is running.

#### Verification Method 3: Container Internal Network Connectivity Test

For WSL2 + Docker scenarios, the n8n container needs to use `host.docker.internal` or the host's LAN IP to access the Windows host. Run the following in an Ubuntu terminal:

```bash
docker exec -it n8n curl -v http://host.docker.internal:2026
```

If it returns `Connected to host.docker.internal` or the DeerFlow HTML page, cross-system networking is working. If you get `Could not resolve host` or `Connection refused`, the network is not yet connected. Refer to Section 5 of this document for configuration.

> **Note**: In subsequent n8n node configurations, the URL should use `host.docker.internal` instead of `localhost`, because `localhost` inside the container points to the container itself, not the Windows host.

---

## 3. Configuring the HTTP Request Node in n8n

### 3.1 Add Node and Basic Parameters

- **Method**: `POST`
- **URL**: `http://<DeerFlow address>:2026/api/langgraph/runs/stream`

### 3.2 Configuring Authentication (Header Auth)

The DeerFlow `/api/langgraph/runs/stream` endpoint uses **Bearer Token** authentication. In n8n, we need to use **Header Auth** credentials to attach the PAT as `Authorization: Bearer dfp_...` to every HTTP request header.

#### 3.2.1 Configuration Steps

1. In the HTTP Request node's **Parameters** panel, find the **Authentication** dropdown and select **Generic Credential Type**.
2. In the newly appeared **Generic Auth Type** dropdown, select **Header Auth**.
3. Click **Create new credential**, or click the dropdown arrow next to Credential for Header Auth and select **Create New**.
4. In the credential editing window, fill in the following two fields:
   - **Name**: `Authorization`
   - **Value**: `Bearer dfp_your_token`

> ⚠️ **Note**: There must be an English space between `Bearer` and the token. If the space is missing, the server will return `401 Unauthorized`.

5. Click **Save** to save the credential.
6. Return to the HTTP Request node and confirm that **Credential for Header Auth** has selected the credential you just created.
7. (Recommended) Turn on the **Send Headers** switch and add:
   - **Name**: `Content-Type`
   - **Value**: `application/json`

#### 3.2.2 Field Description


| Field | Value | Description |
| ----- | ----- | ----------- |
| Name | `Authorization` | HTTP standard authentication header name; cannot be changed |
| Value | `Bearer dfp_...` | Note the space after `Bearer`; the token starts with `dfp_` |

#### 3.2.3 Common Errors and Troubleshooting


| Symptom | Possible Cause | Solution |
| ------- | -------------- | -------- |
| `401 Unauthorized` | Token is wrong, expired, or malformed | Regenerate the PAT and check whether the Value is `Bearer dfp_...` |
| `403 Forbidden` | Token lacks required scopes | Check whether the PAT includes `runs:create` and `runs:read` |
| Connection failed / timeout | Network is unreachable | Refer to Section 5, "Cross-System Network Configuration" |

> **Tip**: If you cannot find the `Header Auth` option in your n8n version, please confirm n8n is updated to the latest version, or check whether the core node package is installed. Usually, `Header Auth` is a built-in generic credential type in n8n and requires no additional installation.

### 3.3 Configuring the Request Body (Send Body)

The request body is the most error-prone part when calling DeerFlow from n8n. The DeerFlow `/api/langgraph/runs/stream` endpoint follows the **LangGraph SDK request protocol**, not a custom simple JSON. If the request body structure is incorrect, the server will directly return `422` or `Extra inputs are not permitted`.

#### 3.3.1 Common Incorrect Format

Many first-time integrators (including the author) naturally write:

```json
{
  "message": "Analyze the price distribution, main selling points, and negative review keywords for Bluetooth earbuds on Amazon US."
}
```

After clicking `Execute step` in n8n, you will receive an error similar to:

```text
Your request is invalid or could not be processed by the service
Extra inputs are not permitted
```

Reason: `/api/langgraph/runs/stream` does not accept the `message` field. It expects the LangGraph standard input structure `input.messages`. Extra fields are directly rejected by Pydantic validation.

#### 3.3.2 Correct Request Body Format

Set `Specify Body` to `Using JSON` and fill in the following structure:

```json
{
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "Analyze the price distribution, main selling points, and negative review keywords for Bluetooth earbuds on Amazon US, and generate a brief report."
      }
    ]
  },
  "config": {
    "recursion_limit": 100
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

Field descriptions:


| Field | Required | Description |
| ----- | -------- | ----------- |
| `input.messages` | ✅ Required | Array of user messages; each message contains `role` and `content`. `role` is usually `user`. |
| `config.recursion_limit` | Recommended | DeerFlow's default recursion limit is 25 steps. Deep research tasks easily exceed this. Set to `100`. |
| `stream_mode` | Recommended | Must be a supported LangGraph mode combination. `values`, `messages-tuple`, `custom` are available in the current version; `messages`, `events`, etc. will return 422. |

#### 3.3.3 Dynamically Injecting Messages in n8n

If you want to dynamically fill `content` with results from upstream nodes (such as a Webhook or database query), you can use n8n expressions. For example:

```json
{
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "{{ $json.user_question }}"
      }
    ]
  },
  "config": {
    "recursion_limit": 100
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

This way, `content` is dynamically read from the `user_question` field passed in from the upstream node.

#### 3.3.4 Verify the Request Body with curl First

Before debugging in n8n, it is recommended to verify the request body in a terminal using `curl`:

```bash
curl -X POST http://localhost:2026/api/langgraph/runs/stream \
  -H "Authorization: Bearer dfp_your_token" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "messages": [{"role": "user", "content": "test"}]
    },
    "config": {"recursion_limit": 100},
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'
```

If `curl` returns the SSE stream normally, the request body structure is correct, and you only need to align the format in n8n. If `curl` also errors, check the field names and values based on the error message.

#### 3.3.5 Common Error Quick Reference


| Error | Cause | Solution |
| ----- | ----- | -------- |
| `Extra inputs are not permitted` | Used `{"message": "..."}` or other non-LangGraph fields | Change to `input.messages` structure |
| `422 Validation Error`, invalid `stream_mode` | Used unsupported `stream_mode`, such as `messages`, `events` | Use `["values", "messages-tuple", "custom"]` |
| `422 Validation Error`, missing `input` | Request body is empty or only contains `message` | Ensure the top level contains the `input` field |
| Request times out after a long time | `recursion_limit` too low, causing task termination mid-way | Set `recursion_limit` to `100` or higher |

---

## 4. Handling Streaming Responses (Handling SSE)

### 4.1 Why Special Handling Is Needed

The DeerFlow `/api/langgraph/runs/stream` endpoint returns a **Server-Sent Events (SSE)** stream, not a one-time JSON response. The raw SSE text format looks like:

```text
event: metadata
data: {"run_id": "..."}

event: values
data: {"messages": [{"content": "..."}]}

event: messages
data: {"content": "..."}

event: end
data: null
```

The n8n HTTP Request node tries to parse the response body as JSON by default. When it receives this multi-line SSE text, it directly throws a `JSON parse error` or `Unexpected token` error. Therefore, you must change the response format to plain text and then manually parse it in subsequent nodes.

### 4.2 Set Response Format = Text

1. In the HTTP Request node, expand the **Options** panel at the bottom.
2. Click **Add option** and find **Response** → **Response Format**.
3. Change the default `JSON` to **`Text`**.
4. Save the settings.

After this change, click `Execute step` again. The n8n OUTPUT panel will show the complete SSE text stream without JSON parsing errors.

### 4.3 Extract Final Content with a Code Node

The SSE text stream contains multiple events; we usually only need the final AI reply content. You can add a **Code node** after the HTTP Request node and use JavaScript to extract and concatenate all `content` fields.

In the SSE `values` event, the `messages` array contains both user messages and AI messages. When parsing, you must distinguish them via the `type` or `role` field and only extract AI message `content`; otherwise, the prompt will be output as-is.

The following code handles common DeerFlow SSE output:

```javascript
// Get the raw SSE text returned by the HTTP Request node
const raw = $input.first().json.data;

const lines = raw.split('\n');
let finalContent = '';

for (let i = 0; i < lines.length; i++) {
  const line = lines[i].trim();

  // Parse the event name
  if (line.startsWith('event:')) {
    const eventName = line.replace(/^event:\s*/, '').trim();
    if (eventName === 'error') {
      // Extract the error message from data and throw to fail the n8n node, instead of silently outputting
      const nextLine = lines[i + 1] ? lines[i + 1].trim() : '';
      if (nextLine.startsWith('data:')) {
        const errDataStr = nextLine.replace(/^data:\s*/, '');
        let errMessage = errDataStr;
        try {
          const errData = JSON.parse(errDataStr);
          errMessage = errData.message || errDataStr;
        } catch (jsonErr) {
          // Ignore JSON parse errors; fall back to the raw string.
        }
        throw new Error(`DeerFlow runtime error: ${errMessage}`);
      }
      throw new Error(`DeerFlow emitted an error event.`);
    }
  }

  if (!line.startsWith('data:')) continue;

  const jsonStr = line.replace(/^data:\s*/, '');
  if (!jsonStr || jsonStr === 'null') continue;

  try {
    const obj = JSON.parse(jsonStr);

    // Handle the messages array in the values event. The values event is a full snapshot,
    // and each update contains the complete history. Only the last AI message is needed
    // as the output for the current step.
    if (obj.messages && Array.isArray(obj.messages)) {
      const aiMessages = obj.messages.filter(
        (msg) => msg.type === 'ai' || msg.role === 'assistant' || msg.type === 'AIMessage'
      );
      if (aiMessages.length > 0) {
        const lastAiMsg = aiMessages[aiMessages.length - 1];
        // Overwrite instead of appending to avoid duplicating historical messages.
        if (lastAiMsg.content) {
          if (Array.isArray(lastAiMsg.content)) {
            // Extract and join text blocks if content is an array
            finalContent = lastAiMsg.content
              .filter((block) => block.type === 'text')
              .map((block) => block.text)
              .join('');
          } else {
            // Handle the string-content path
            finalContent = lastAiMsg.content;
          }
        }
      }
    }

    // Handle messages-tuple event (if the AI reply is here)
    if (obj.type === 'ai' || obj.role === 'assistant') {
      if (obj.content) finalContent += obj.content;
    }
  } catch (e) {
    // Ignore lines that cannot be parsed
  }
}

return { content: finalContent.trim() };
```

Paste this code into the Code node. After execution, you will get the plain-text analysis report. You can then connect Feishu, email, database, or other nodes for distribution or storage.

> **Tip**: If your DeerFlow version returns different event types, first use `console.log` to print the raw `raw` text and observe the actual structure before adjusting the parsing logic.

### 4.4 Alternative Solutions

If you do not want to handle SSE streams, you can try the following alternatives:

- **Use the n8n community Streaming HTTP Request node**: This node natively supports SSE and can directly receive streaming responses and output them one by one. Requires installing an additional community node package.
- **Use the non-streaming endpoint (`/api/runs/wait`)**: The Gateway already exposes `/api/runs/wait` for workflows that only need the final completed result. Using this endpoint simplifies the HTTP Request node, as it returns a standard JSON response instead of an SSE stream. You can configure the HTTP Request node normally with `Response Format: JSON` and extract the final message directly without a custom Code parser.

  ```json
  {
    "input": {
      "messages": [{ "role": "user", "content": "..." }]
    },
    "config": { "recursion_limit": 100 }
  }
  ```
- **Temporarily reduce streaming complexity**: Set `stream_mode` to `["values"]` in the request body to keep only the final value event and reduce the number of intermediate events. However, you still need to receive it as Text and parse it.

---

## 5. Cross-System Network Configuration (Windows + WSL2 Scenario)

### 5.1 Problem Description

When DeerFlow runs on the **Windows host** and n8n runs in a **WSL2 Docker container**, they are in different network namespaces. Inside the n8n container, `localhost` points to the container itself and cannot access `localhost:2026` on Windows. Therefore, you must use an address that can route to the Windows host.

Our actual testing found that `host.docker.internal` cannot be resolved in some WSL2 configurations (error `Could not resolve host`). In that case, you need to use the WSL2 virtual NIC IP or the Windows LAN IP.

### 5.2 Solution A: Use `host.docker.internal`

`host.docker.internal` is a special domain provided by Docker Desktop for Windows to access the host from inside a container.

Applicable condition: Docker Desktop has WSL2 backend enabled and is a relatively new version.

Verification method: Run the following in a WSL2 Ubuntu terminal:

```bash
docker exec -it n8n curl -v http://host.docker.internal:2026
```

If it returns `Connected to host.docker.internal` or the DeerFlow HTML page, it is available. In the n8n HTTP Request node, the URL can be:

```text
http://host.docker.internal:2026/api/langgraph/runs/stream
```

If you get `Could not resolve host`, use Solution B.

### 5.3 Solution B: Use the WSL2 Virtual NIC IP or Windows LAN IP

#### Step 1: Get the Correct IP Address

There are two available IPs:

- **WSL2 virtual NIC IP**: Run in a WSL2 Ubuntu terminal:

  ```bash
  cat /etc/resolv.conf | grep nameserver
  ```

  The `nameserver <WSL2_HOST_IP>` in the output is the Windows host's virtual NIC IP. This IP may change after each WSL2 restart.
- **Windows LAN IP**: Run `ipconfig` in Windows PowerShell or CMD and find the IPv4 address under "Wireless LAN adapter WLAN" (e.g., `192.168.x.x`). This IP is relatively stable within the LAN but may change after a router restart.

It is recommended to prefer the WSL2 virtual NIC IP because it is a dedicated channel between WSL2 and the host and is not affected by external networks.

#### Step 2: Allow Windows Firewall

Regardless of which IP you use, you must ensure Windows Firewall allows inbound connections on port 2026:

1. Search for "Windows Defender Firewall" → Advanced settings.
2. Click "Inbound Rules" → "New Rule".
3. Rule type: "Port" → TCP → Specific local port: `2026`.
4. Select "Allow the connection" → Check all (Domain, Private, Public).
5. Name it (e.g., `DeerFlow`) and save.

#### Step 3: Fill in the URL in n8n

Change the HTTP Request node URL to:

```text
http://<WSL2_HOST_IP>:2026/api/langgraph/runs/stream
```

Replace `<WSL2_HOST_IP>` with the IP you actually obtained.

### 5.4 Connectivity Test

Before modifying the n8n configuration, it is recommended to verify network connectivity in a WSL2 terminal first:

```bash
# Directly test the host IP
curl -v http://<WSL2_HOST_IP>:2026

# Or test from inside the n8n container
docker exec -it n8n curl -v http://<WSL2_HOST_IP>:2026
```

If it returns an HTML page or `Connected to ...`, the network is working. If it still fails, check:

- Whether Windows Firewall allows port 2026.
- Whether DeerFlow is running (`http://localhost:2026` is accessible in a Windows browser).
- Whether the IP address is correct (the WSL2 virtual NIC IP may change after each restart and needs to be re-obtained).

> **Note**: In the n8n HTTP Request node, the URL cannot be `localhost:2026`, because that points to the container itself. You must use `host.docker.internal` or an explicit IP address.

---

## 6. Troubleshooting

This chapter lists common errors, causes, and solutions during integration.

### 6.1 403 Forbidden / CSRF token missing

**Cause**: Non-browser requests lack the CSRF Token. This should disappear after using a PAT.

**Solution**: Check whether the Header is `Authorization: Bearer dfp_...` and confirm the PAT is valid.

### 6.2 401 Unauthorized

**Cause**: Token is wrong, expired, or malformed.

**Solution**: Regenerate the PAT and check whether the Value is `Bearer dfp_...`. Note the space after `Bearer`.

### 6.3 503 Service Unavailable

**Cause**: Database backend is `memory`.

**Solution**: Refer to the [Database Configuration Guide](CONFIGURATION.md#database-backend) to switch to SQLite or PostgreSQL.

### 6.4 ECONNREFUSED / ETIMEDOUT

**Cause**: Network is unreachable.

**Solution**: Go back to Section 5 and check cross-system communication. Confirm the URL uses `host.docker.internal` or the correct IP.

### 6.5 JSON parse error

**Cause**: Response Format was not changed to Text.

**Solution**: In the HTTP Request node's Options → Response → Response Format, select `Text`.

### 6.6 PAT Creation Failed: 422 Validation Error

**Symptom**: Calling `POST /api/v1/auth/login/local` returns:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "username"],
      "msg": "Field required",
      "input": null
    },
    {
      "type": "missing",
      "loc": ["body", "password"],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

**Cause**: DeerFlow's local login endpoint expects the field name `username`, not `email`; and the request body should use form encoding, not JSON.

**Solution**:

- Use `data={"username": ..., "password": ...}` to send the request.
- Change the CLI argument from `--email` to `--username`.
- If using a Python script, refer to Section 2.4 Automating PAT Creation.

### 6.7 SSE Returns `Invalid IPv6 address: '[workspace-id]'`

**Symptom**: The n8n node executes successfully (HTTP 200), but the SSE response contains `event: error` with the message `Invalid IPv6 address: '[workspace-id]'`.

**Cause**: The `base_url` in the model configuration in `config.yaml` contains an unreplaced placeholder `[workspace-id]`. When httpx parses the URL, it mistakes the bracketed content for an IPv6 address, causing parsing failure.

**Solution**: Replace `base_url` with the real API address.

### 6.8 `uv trampoline failed to canonicalize script path`

**Symptom**: After modifying the DeerFlow project path (e.g., removing spaces or renaming a parent directory), running `make dev` reports:

```text
error: uv trampoline failed to canonicalize script path
make: *** [Makefile:147: dev] Error 1
```

**Cause**: The Python virtual environment `.venv` hardcodes the absolute path at creation time. When the project directory is moved or renamed, the old path becomes invalid, and `uv` cannot find the correct Python interpreter through the trampoline script in the virtual environment.

**Solution**: Delete the old virtual environment and reinstall dependencies.

1. Stop the running DeerFlow service (press `Ctrl+C`).
2. Delete the `backend/.venv` directory:

   ```bash
   rm -rf backend/.venv
   ```

   If using Windows File Explorer, you can manually delete the `deer-flow/backend/.venv` folder.
3. Reinstall dependencies:

   ```bash
   make install
   ```
4. Restart the service:

   ```bash
   make dev
   ```

**Additional note**: If similar errors still occur after reinstallation, close the current terminal and reopen it to ensure environment variables do not cache the old path. Also, it is recommended to keep the project path concise and avoid spaces and special characters to reduce such issues.

### 6.9 Docker (WSL2) Network Failure Causes DNS Resolution Failure

**Symptom**: The n8n node reports `The DNS server returned an error, perhaps the server is offline`, or testing the network in a WSL2 terminal reports `Error: fetch failed`.

**Cause**: The Docker container DNS configuration under WSL2 is invalid, and the container cannot resolve external domain names (such as `api.apify.com`). This is very common after restarting the computer or switching network environments.

**Solution**:

Solution A (Recommended): Force DNS in `docker-compose.yml`.

Add the `dns` configuration under the n8n service and recreate the container:

```yaml
services:
  n8n:
    image: n8nio/n8n:latest
    restart: unless-stopped
    ports:
      - "5678:5678"
    dns:
      - 8.8.8.8
      - 1.1.1.1
    environment:
      - GENERIC_TIMEZONE=Asia/Shanghai
      - TZ=Asia/Shanghai
```

```bash
docker compose down
docker compose up -d
```

Solution B: Manually fix WSL2's `/etc/resolv.conf`.

Open an Ubuntu terminal:

```bash
sudo nano /etc/resolv.conf
```

Change the `nameserver` to:

```text
nameserver 8.8.8.8
nameserver 1.1.1.1
```

Save and exit, then restart WSL (run `wsl --shutdown` in Windows PowerShell), reopen the Ubuntu terminal, and start the n8n container.

How to verify the fix: Run the following in a WSL2 terminal. If it returns status code 200, DNS is fixed:

```bash
docker exec n8n node -e "fetch('https://api.apify.com').then(r => console.log('Status:', r.status)).catch(e => console.error('Error:', e.message))"
```

### 6.10 Apify Error `Invalid input: No input provided`

**Symptom**: The n8n node executes successfully (HTTP 200), but the Apify console's Runs page shows status `Invalid input` and Results is 0.

**Cause**: The request body lacks a specific scraping type (such as `Product Details` or `Search`) and only provides the target URL. Apify's `e-commerce-scraping-tool` needs to be explicitly told what to scrape and how.

**Solution**:

1. Open the corresponding Actor page in the Apify console.
2. Click **Start** and configure the scraping parameters in the visual interface (e.g., select `Product Details` and enter the target URL).
3. Switch to the **JSON** view and copy the generated complete JSON.
4. Paste it back into the n8n HTTP Request Body and re-execute.

Reference complete JSON example (scraping product details):

```json
{
  "detailsUrls": [
    {
      "url": "https://www.amazon.com/dp/B002MSN3QQ"
    }
  ],
  "additionalProperties": true,
  "additionalReviewProperties": true
}
```

### 6.11 DeerFlow Receives Unrendered Template Variable (`{{ JSON.stringify($json) }}`)

**Symptom**: DeerFlow prompts "no data found" or "unrendered template variable" during analysis, or the final email contains the literal `{{ JSON.stringify($json) }}`.

**Cause**: In the n8n HTTP Request node, the `JSON` input box is in **`Fixed`** mode by default. In this mode, n8n treats `{{ }}` as a plain string and does not parse it. Therefore, DeerFlow receives only that string, not the actual data.

**Solution**:

Solution A (Recommended, most reliable): Use a Code node to dynamically build the request body.

Insert a **Code in JavaScript** node between Apify and DeerFlow, and use JavaScript to concatenate the data into a complete request body.

Code node example:

```javascript
// Get the data scraped by the upstream Apify node
const apifyData = $input.first().json;

// Build the prompt containing the actual data
const prompt = "You are a senior e-commerce market analyst. Please analyze the following competitor data from three dimensions: product portfolio gaps, pricing weaknesses, and bundle sales opportunities. Identify market opportunities we can exploit and score each opportunity by priority (1-10). The data is as follows: " + JSON.stringify(apifyData);

// Output the standard DeerFlow / LangGraph request body
return {
  json: {
    input: {
      messages: [
        { role: "user", content: prompt }
      ]
    },
    config: { recursion_limit: 100 },
    stream_mode: ["values", "messages-tuple", "custom"]
  }
};
```

HTTP Request node configuration:

1. `Send Body` → `Specify Body` select `Using JSON`.
2. **Key**: Click the `Fixed` in the upper right corner of the JSON input box and switch to **`Expression`** mode.
3. Enter `{{ $json }}` in the input box.

Solution B (only for simple scenarios): Use n8n expressions directly in the Body.

If you do not want to add a Code node, you can try writing a JSON expression directly in the Body box, but you must switch the mode to `Expression`:

```json
{
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "You are an e-commerce analyst. Please analyze the following data: {{ JSON.stringify($json) }}"
      }
    ]
  },
  "config": { "recursion_limit": 100 },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

> **Note**: Solution B may still fail to parse due to escaping issues in some n8n versions. Solution A (Code node + `{{ $json }}`) is the most recommended and reliable approach.

### 6.12 Troubleshooting Quick Reference


| Error | Possible Cause | Corresponding Section |
| ----- | -------------- | --------------------- |
| `The DNS server returned an error` / `fetch failed` | Docker/WSL2 container DNS resolution failure | 6.9 |
| Apify reports `Invalid input: No input provided` | Request body missing `detailsUrls` / `urls` parameters | 6.10 |
| DeerFlow prompts "no data found" or outputs `{{ }}` | n8n JSON Body not using Expression mode | 6.11 |
| `Extra inputs are not permitted` | Request body uses `{"message": "..."}` or other non-LangGraph fields | 3.3 |
| `403 Forbidden` / `CSRF token missing` | PAT not used, or Token format is incorrect | 3.2 / 6.1 |
| `Invalid IPv6 address: '[workspace-id]'` | `config.yaml` `base_url` or `work_dir` contains unreplaced placeholders | 6.7 |
| `uv trampoline failed to canonicalize script path` | `.venv` invalid after modifying project path | 6.8 |

### 6.13 Parsing SSE Mistakenly Outputs the Prompt as the AI Reply

**Symptom**: The workflow executes successfully and the email is sent normally, but the email body shows the original prompt sent to DeerFlow, not the AI analysis report generated by DeerFlow. For example, the email contains "You are a senior e-commerce market analyst. Please analyze the following competitor data..." instead of the analysis results for the data.

**Cause**: In the SSE stream returned by DeerFlow, the `messages` array carried by the `event: values` event contains both user messages and AI messages. The old parsing code did not distinguish message types and directly concatenated all `content` fields in the `messages` array, causing the user message (prompt) to be output as the AI reply.

Specifically, in the SSE `values` event, the `messages` array structure is similar to:

```json
{
  "messages": [
    {
      "content": "You are a senior e-commerce market analyst...",
      "type": "human",
      "role": "user"
    },
    {
      "content": "Based on the competitor data you provided, I analyze from three dimensions...",
      "type": "ai",
      "role": "assistant"
    }
  ]
}
```

The old code only checked whether `msg.content` existed and did not further check `msg.type` or `msg.role`, so it also concatenated the `content` of the `human` message into the final output.

**Solution**: When parsing the `messages` array, extract only the content of AI messages. The condition is:

- `msg.type === 'ai'`
- or `msg.role === 'assistant'`
- or `msg.type === 'AIMessage'`

At the same time, for `event: messages-tuple` or events that directly return `content`, also ensure that only AI-related parts are extracted.

Corrected parsing code:

```javascript
const raw = $input.first().json.data;
const lines = raw.split('\n');
let finalContent = '';

for (let i = 0; i < lines.length; i++) {
  const line = lines[i].trim();

  // Parse the event name
  if (line.startsWith('event:')) {
    const eventName = line.replace(/^event:\s*/, '').trim();
    if (eventName === 'error') {
      // Extract the error message from data and throw to fail the n8n node, instead of silently outputting
      const nextLine = lines[i + 1] ? lines[i + 1].trim() : '';
      if (nextLine.startsWith('data:')) {
        const errDataStr = nextLine.replace(/^data:\s*/, '');
        let errMessage = errDataStr;
        try {
          const errData = JSON.parse(errDataStr);
          errMessage = errData.message || errDataStr;
        } catch (jsonErr) {
          // Ignore JSON parse errors; fall back to the raw string.
        }
        throw new Error(`DeerFlow runtime error: ${errMessage}`);
      }
      throw new Error(`DeerFlow emitted an error event.`);
    }
  }

  if (!line.startsWith('data:')) continue;

  const jsonStr = line.replace(/^data:\s*/, '');
  if (!jsonStr || jsonStr === 'null') continue;

  try {
    const obj = JSON.parse(jsonStr);

    // Handle the messages array in the values event. The values event is a full snapshot,
    // and each update contains the complete history. Only the last AI message is needed
    // as the output for the current step.
    if (obj.messages && Array.isArray(obj.messages)) {
      const aiMessages = obj.messages.filter(
        (msg) => msg.type === 'ai' || msg.role === 'assistant' || msg.type === 'AIMessage'
      );
      if (aiMessages.length > 0) {
        const lastAiMsg = aiMessages[aiMessages.length - 1];
        // Overwrite instead of appending to avoid duplicating historical messages.
        if (lastAiMsg.content) {
          if (Array.isArray(lastAiMsg.content)) {
            // Extract and join text blocks if content is an array
            finalContent = lastAiMsg.content
              .filter((block) => block.type === 'text')
              .map((block) => block.text)
              .join('');
          } else {
            // Handle the string-content path
            finalContent = lastAiMsg.content;
          }
        }
      }
    }

    // Handle messages-tuple event (if the AI reply is here)
    if (obj.type === 'ai' || obj.role === 'assistant') {
      if (obj.content) finalContent += obj.content;
    }
  } catch (e) {
    // Ignore lines that cannot be parsed
  }
}

return { content: finalContent.trim() };
```

**Verification method**: Check the returned `content` field in the Code node OUTPUT. If the output is the AI analysis report and no longer contains prompts like "You are a senior e-commerce market analyst", the parsing logic has been corrected.

**Additional notes**:

- If you use `stream_mode: ["values", "messages-tuple", "custom"]` in DeerFlow's SSE, note that both `values` and `messages-tuple` events may contain AI replies, but the `messages` array in `values` contains both user and AI messages.
- If only `messages-tuple` mode is used, the `messages` array will not appear, and the parsing logic needs to be adjusted accordingly.
- It is recommended to include a check for `type` in the parsing code rather than relying only on `role`, because LangChain may use `type` or `role` fields in different versions.

---

## 7. Security Best Practices

When integrating DeerFlow into a production n8n environment, security is a critical aspect. Since n8n workflows contain a large amount of business logic and API interactions, once a PAT is leaked, it may be maliciously exploited. This section provides several core security best practices.

### 7.1 Principle of Least Privilege

Never use an administrator's PAT, and do not share a personal account's PAT. It is recommended to create a dedicated user or system account for n8n and generate a PAT only for it.

- **Required scopes**: Select only `runs:create` and `runs:read`. Never grant `user:admin` or other unrelated high-risk permissions.
- **Isolation**: This way, even if n8n credentials are accidentally leaked, attackers can only initiate analysis tasks and cannot modify system configurations or delete data.

### 7.2 Regular Token Rotation

PATs have an expiration date; not rotating them for a long time increases the risk of leakage.

- **Set expiration time**: When creating a PAT, it is recommended to set `expires_in_days` (e.g., 90 days).
- **Rotation strategy**: Before expiration, generate a new PAT, update the `Header Auth` Value in n8n's credential manager, and then revoke the old PAT.
- **Automated reminder**: You can use n8n itself to create a "token expiration reminder" workflow to periodically check the remaining validity of the PAT.

### 7.3 Secure Credential Storage

Never hardcode the PAT in workflow JSON or code nodes. n8n provides a secure credential manager.

- As described in Section 3.2, create a `Header Auth` credential in n8n and store `Bearer dfp_...` in the credential.
- Reference the credential in the workflow, so even if you export and share the workflow JSON, the token will not be leaked.
- If using environment variables, ensure the permissions of n8n's `.env` file are strictly controlled.

### 7.4 Revoke Tokens

If you suspect a token has been leaked, or the n8n workflow no longer needs to access DeerFlow, revoke the PAT immediately.

- **Revoke via UI**: Log in to the DeerFlow frontend, go to the settings or profile page, find the "Personal Access Tokens" management interface, and click revoke.
- **Revoke via API**: If DeerFlow provides a revocation endpoint (such as `DELETE /api/v1/auth/pats/{id}`), you can call it directly via an HTTP Request node. After revocation, all n8n workflows relying on that PAT will immediately return `401 Unauthorized`, preventing unauthorized access.

---

## 8. Complete Workflow Example

To connect the knowledge points from the previous chapters, this section provides a complete, runnable end-to-end workflow example: **Daily Competitor Price Monitoring and AI Analysis Report**.

**Business logic**: Automatically trigger at 9:00 AM every day, call Apify to scrape Amazon competitor data, send the data to DeerFlow for deep analysis, extract the AI report, and send it to the operations team via email.

**Node chain**:

```text
Schedule Trigger
  → HTTP Request1 (Apify)
  → Code in JavaScript1
  → HTTP Request (DeerFlow)
  → Code in JavaScript
  → Send an Email
```

### 8.1 Node Configuration Details

#### Node 1: Schedule Trigger

- Configuration: Set to execute at 9:00 AM every day. This is the starting point of the entire workflow, ensuring the latest data is obtained regularly.

#### Node 2: HTTP Request1 (Call Apify to Scrape Data)

- **Method**: POST
- **URL**: Fill in your Apify Actor endpoint, e.g., `https://api.apify.com/v2/acts/.../run-sync-get-dataset-items`.
- **Authentication**: Use the Apify API Token, configured as Header Auth or Query Auth in n8n.
- **Send Body**: Refer to Section 6.10. Must include the complete JSON, such as:

```json
{
  "detailsUrls": [
    {
      "url": "https://www.amazon.com/dp/B002MSN3QQ"
    }
  ],
  "additionalProperties": true,
  "additionalReviewProperties": true
}
```

If the specific scraping type is missing, Apify will return `Invalid input`.

- **Output**: This node returns the scraped product detail JSON array.

#### Node 3: Code in JavaScript1 (Build DeerFlow Request Body)

- **Purpose**: Corresponds to Section 6.11. To prevent n8n from sending `{{ }}` as a string in JSON mode, you must use JS here to concatenate the actual prompt and Apify data.
- **Code example**:

```javascript
// Get the data scraped by the upstream Apify node
const apifyData = $input.first().json;

// Build the prompt containing the actual data (adjust the prompt as needed)
const prompt = "You are a senior e-commerce market analyst. Please analyze the following competitor data from three dimensions: product portfolio gaps, pricing weaknesses, and bundle sales opportunities. Identify market opportunities we can exploit and score each opportunity by priority (1-10). The data is as follows: " + JSON.stringify(apifyData);

// Output the standard DeerFlow / LangGraph request body
return {
  json: {
    input: {
      messages: [
        { role: "user", content: prompt }
      ]
    },
    config: { recursion_limit: 100 },
    stream_mode: ["values", "messages-tuple", "custom"]
  }
};
```

#### Node 4: HTTP Request (Call DeerFlow)

- **Method**: POST
- **URL**: `http://<WSL2_HOST_IP>:2026/api/langgraph/runs/stream`. Note: As described in Section 5, `localhost` cannot be used in WSL2. Replace it with your actual IP or `host.docker.internal`.
- **Authentication**: Select the `Header Auth` credential created in Section 3.2, with value `Bearer dfp_...`.
- **Send Body**: Select `Using JSON`. Key step: Switch the `Fixed` in the upper right corner to **`Expression`** mode, then enter `{{ $json }}`. This will read the complete JSON output by the previous Code node.
- **Options**: Expand Options and change **Response Format** to **Text**, corresponding to Section 4.2, otherwise a JSON parsing error will occur.
- **Timeout**: Set to `300000`, i.e., 5 minutes, because DeerFlow deep analysis takes a long time.

#### Node 5: Code in JavaScript (Extract AI Reply)

- **Purpose**: Corresponds to Sections 4.3 and 6.13. Parse the raw SSE text and must filter out user messages (prompts), extracting only AI messages.
- **Code example**: Directly copy the "Corrected parsing code" from Section 6.13. Make sure it includes the check `if (msg.type === 'ai' || msg.role === 'assistant')`, otherwise the email body may become the prompt you sent to DeerFlow.

#### Node 6: Send an Email (Send Report)

- **Configuration**: Select SMTP credentials, set recipients, subject, e.g., `Daily Competitor Price Analysis Report - {{ $now.format('yyyy-MM-dd') }}`.
- **Email body**: Use the `content` field output by the previous Code node, i.e., `{{ $json.content }}`. You can format it as HTML for readability.

> **Tip**: If your workflow also needs to send to a Feishu group, you can replace Node 6 with Feishu's Webhook node and similarly reference `{{ $json.content }}`.

### 8.2 Verification and Debugging

1. **Manual execution**: Click the `Execute workflow` button in n8n and observe the output of each node.
2. **Check Code node**: In the output of Node 3, confirm that the `content` field contains the real Apify data, not the literal `{{ JSON.stringify($json) }}`.
3. **Check SSE parsing**: In the output of Node 5, confirm that `content` is the AI analysis report and does not contain the prompt "You are a senior e-commerce market analyst..." that you wrote.
4. **Check email**: Check the inbox to ensure the report is complete and correctly formatted.

---

## 9. Appendix

### 9.1 Related Official Documentation Links

- [API Reference — Personal Access Tokens](API.md#personal-access-tokens)
- [Database Configuration Guide — Database Backend](CONFIGURATION.md#database-backend)
- [DeerFlow Gateway Authentication](API.md#authentication)

### 9.2 n8n Node Parameter Quick Reference


| Node Type | Parameter | Recommended Value / Description |
| --------- | --------- | ------------------------------- |
| **HTTP Request (DeerFlow)** | Method | `POST` |
| | URL | `http://<DeerFlow address>:2026/api/langgraph/runs/stream` |
| | Authentication | `Generic Credential Type` → `Header Auth` |
| | Header Auth Name | `Authorization` |
| | Header Auth Value | `Bearer dfp_your_token`, note the space |
| | Send Body | `Using JSON`, and switch to `Expression` mode |
| | Body content | `{{ $json }}` |
| | Response Format | `Text`, Options → Response |
| | Timeout | `300000`, 5 minutes |
| **Code (Build Request Body)** | Language | JavaScript |
| | Return value | JSON object containing `input.messages`, `config.recursion_limit`, `stream_mode` |
| **Code (Parse SSE)** | Language | JavaScript |
| | Extraction logic | Iterate over `data:` lines, parse JSON, filter `type === 'ai'` or `role === 'assistant'` |

### 9.3 FAQ

**Q1: Can I use a PAT to create a new PAT?**

No. For security reasons, PAT creation must be done through an interactive session (such as logging in via a browser and obtaining a CSRF Token). A PAT cannot be used to silently generate a new PAT. This prevents infinite cascading leakage of tokens.

**Q2: Why can't DeerFlow's request body use `{"message": "..."}`?**

Because `/api/langgraph/runs/stream` follows the LangGraph SDK request protocol and expects the `input.messages` array structure. Extra fields are directly rejected by Pydantic validation, returning `Extra inputs are not permitted`. Please refer to Section 3.3.2 for the correct format.

**Q3: n8n executes successfully (HTTP 200), but the Apify console shows `Invalid input`. Why?**

This indicates the network request went through, but the Apify Actor did not receive the correct scraping parameters. Please refer to Section 6.10. After configuring the parameters visually in the Apify console, copy the complete JSON and replace the request body in n8n.

**Q4: Why is the email content the prompt instead of the AI analysis report?**

This is because when parsing SSE, `human` and `ai` messages were not distinguished. Please refer to Section 6.13. In the Code node, add the check `if (msg.type === 'ai' || msg.role === 'assistant')` to extract only the AI reply content.