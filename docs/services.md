# CSC Services Documentation

## Overview

Services are pluggable modules that extend CSC server functionality. Each service exposes commands via the `AI <token> <service> <command> [args]` interface or direct invocation from IRC clients.

---

## Core Services

### Backup Service

**Name:** `backup`  
**Purpose:** Create, list, restore, and diff backup archives of files and directories.

#### Commands

**`backup.create <path> [path2] [path3] ...`**
- Creates a compressed tar.gz archive of specified files/directories
- Stores archive in `<PROJECT_ROOT>/backups/`
- Returns archive filename and summary
- Updates internal backup history metadata
- **Args:** One or more file/directory paths
- **Returns:** Archive name, file count, size
- **Errors:** No paths specified, path does not exist

**`backup.list`**
- Lists all backup archives with sizes
- Shows creation dates and file counts
- **Args:** None
- **Returns:** Table of archives, total count
- **Errors:** None (returns "no archives found" if empty)

**`backup.restore <archive.tar.gz> <destination_dir>`**
- Extracts archive to destination directory
- Creates destination if it doesn't exist
- **Args:** Archive filename, restore path
- **Returns:** Restored files summary
- **Errors:** Archive not found, path traversal attempt, extraction failure

**`backup.diff <archive.tar.gz> <current_file_path>`**
- Shows unified diff between archived and current version
- Useful for comparing changes
- **Args:** Archive name, current file path
- **Returns:** Unified diff format output
- **Errors:** Archive not found, file not in archive, file doesn't exist

**`backup.default [args]`**
- Shows help message and available commands
- **Args:** Optional (any args show help)
- **Returns:** Command reference and backup directory location

#### External Dependencies
- **Python stdlib:** `tarfile`, `pathlib`, `difflib`, `time`
- **System:** tar/gzip (or Python's built-in tarfile module)

#### Key Features
- Atomic tar.gz creation with timestamp naming
- Path traversal protection on restore
- Metadata tracking in backup_history.json
- File size calculations (B, KB, MB)
- Nested directory support

---

## Security & Identity Services

### CryptServ (Cryptographic Key Distribution)

**Name:** `cryptserv`  
**Purpose:** Certificate Authority (CA) for RSA key pair distribution, issuing keys for channels and direct message pairs.

#### Public Methods Reference

**Class: `CryptServ(Service)`**

All methods inherit from `Service` base class and have access to `self.server`, `self.name`, `self.get_data()`, `self.put_data()`.

##### `__init__(self, server_instance: Server)`
- **Purpose:** Initialize CryptServ service with server instance
- **Args:**
  - `server_instance`: The CSC server instance
- **Behavior:**
  - Calls `super().__init__(server_instance)`
  - Sets `self.name = "cryptserv"`
  - Initializes persistent data via `self.init_data("cryptserv_data.json")`
  - Creates `certs/` directory if it doesn't exist
  - Resolves path to `scripts/gencert.sh`
  - Initializes `issued_certs` dict in persistent data if empty
  - Logs initialization with certs directory path
- **Returns:** None
- **Raises:** OSError if certs directory creation fails

##### `request(self, target: str, requestor_nick: str) -> str`
- **Purpose:** Request or retrieve a certificate (RSA key pair) for a channel or DM pair
- **Args:**
  - `target` (string): Channel name (e.g., `#general`) or sorted DM pair (e.g., `alice:bob`)
  - `requestor_nick` (string): The IRC nick of the client requesting the certificate
- **Returns:** Status message (string)
  - Success: `"Certificate for '<target>' sent to <requestor_nick>."`
  - Errors: Error message with description
- **Behavior:**
  1. Logs the certificate request
  2. Loads issued_certs metadata from persistent storage
  3. Checks if certificate already exists for target
  4. If exists: Loads certificate bundle and sends to requestor
  5. If not exists: 
     - Calls `_run_gencert_script(target)` to generate new keys
     - Returns error if generation fails
     - Loads generated certificate bundle
     - Returns error if bundle cannot be loaded
     - Stores metadata (issued_at timestamp, paths) in issued_certs
     - Persists updated issued_certs to storage
     - Logs certificate issuance
     - Sends certificate bundle to requestor
  6. Sends two PRIVMSG messages to requestor:
     - `CRYPT_PRIVATE <target> :<private_key_pem>` (encrypted by server)
     - `CRYPT_PUBLIC <target> :<public_key_pem>` (encrypted by server)
- **Errors:**
  - "Certificate generation failed..." - gencert.sh execution error
  - "Failed to load generated certificate..." - File I/O error after generation
  - "Requestor '<nick>' not found..." - Requestor not in connected clients (disconnected)
- **Side Effects:**
  - Creates certificate files on disk (certs/<target>/{private,public}.pem)
  - Updates and persists issued_certs metadata
  - Sends encrypted messages to requestor
  - Logs all operations

##### `_run_gencert_script(self, target_name: str) -> tuple[bool, str]`
- **Purpose:** Execute gencert.sh script to generate RSA key pair
- **Args:**
  - `target_name` (string): Target (channel or DM pair) to generate keys for
- **Returns:** Tuple of (success: bool, message: str)
  - Success: `(True, "Certificate generated successfully.")`
  - Error: `(False, "Error: <description>")`
- **Behavior:**
  1. Checks if gencert.sh exists at configured path
  2. If not found: Logs error and returns False
  3. Constructs command: `["wsl", "bash", <gencert_path>, <target_name>]`
  4. Executes subprocess with `capture_output=True, text=True, check=True`
  5. Logs stdout output
  6. Logs any stderr as warning
  7. Returns True on success
  8. Catches CalledProcessError: Logs error and stderr, returns False
  9. Catches other exceptions: Logs unexpected error, returns False
- **Errors:**
  - gencert.sh not found at expected path
  - Script execution failed (non-zero exit code)
  - Script not found by bash
  - Unexpected subprocess exceptions
- **External Dependencies:**
  - WSL bash on Windows (`wsl bash` command)
  - `scripts/gencert.sh` script (must be executable)
- **Note:** WSL requirement is Windows-specific; may need platform detection for cross-platform support

##### `_load_cert_bundle(self, target_name: str) -> dict | None`
- **Purpose:** Load private and public RSA keys from disk for a target
- **Args:**
  - `target_name` (string): Target (channel or DM pair) to load keys for
- **Returns:** Certificate bundle dict or None
  - Success: `{"private": <private_key_pem>, "public": <public_key_pem>}`
  - Not found: `None`
- **Behavior:**
  1. Constructs paths: `certs/<target_name>/{private,public}.pem`
  2. Checks if both files exist
  3. If either missing: Returns None
  4. Opens and reads private.pem file
  5. Opens and reads public.pem file
  6. Returns dict with both keys as strings
- **Errors:**
  - File not found: Returns None (not an error case, handled by caller)
  - File I/O error: Exception propagates to caller
- **Side Effects:** None (read-only)

##### `_send_cert_bundle_to_requestor(self, cert_bundle: dict, target: str, requestor_nick: str) -> str`
- **Purpose:** Send certificate bundle to requestor via encrypted IRC messages
- **Args:**
  - `cert_bundle` (dict): Certificate bundle with "private" and "public" keys
  - `target` (string): Target name (for logging)
  - `requestor_nick` (string): IRC nick of requestor
- **Returns:** Status message (string)
  - Success: `"Certificate for '<target>' sent to <requestor_nick>."`
  - Error: `"Error: Requestor '<nick>' not found..."`
- **Behavior:**
  1. Serializes cert_bundle to JSON string (not currently used in return)
  2. Searches `server.clients` dict for client with matching nick
  3. If not found: Returns error message
  4. If found: 
     - Calls `server.send_privmsg_to_client(addr, "cryptserv", nick, message)` twice:
       - First with `CRYPT_PRIVATE <target> :<private_key_pem>`
       - Second with `CRYPT_PUBLIC <target> :<public_key_pem>`
     - Logs success message
     - Returns success message
- **Errors:**
  - Requestor not in server.clients (nick not found)
  - Server method call failures (propagate to caller)
- **Side Effects:**
  - Sends two encrypted IRC messages to requestor
  - Logs certificate bundle transmission

##### `default(self, *args) -> str`
- **Purpose:** Default handler for unknown CryptServ commands (fallback)
- **Args:**
  - `*args`: Variable arguments (ignored)
- **Returns:** Help message string: `"CryptServ commands: REQUEST <target>"`
- **Behavior:**
  - Simply returns a formatted help string
  - No state changes or side effects
- **Usage:** Called when IRC command handler doesn't recognize the command

#### Commands

**`cryptserv.request <target> <requestor_nick>`**
- Requests a certificate (RSA key pair) for a channel or DM pair
- **Syntax:** `AI <token> cryptserv request #channel` or `AI <token> cryptserv request alice:bob`
- **Args:**
  - `target` (string): Channel name (e.g., `#general`) or sorted DM pair (e.g., `alice:bob`)
  - `requestor_nick` (string): The IRC nick requesting (typically set by IRC handler)
- **Returns:** Status message + separate encrypted PRIVMSG with certificate bundle
- **Behavior:**
  - Checks if certificate already exists; if so, loads and returns it
  - Generates new RSA key pair via `gencert.sh` script if needed
  - Stores metadata in `cryptserv_data.json`
  - Sends private key via secure encrypted PRIVMSG (`CRYPT_PRIVATE`)
  - Sends public key via secure encrypted PRIVMSG (`CRYPT_PUBLIC`)
- **Errors:**
  - `"Certificate generation failed..."` - gencert.sh not found or execution error
  - `"Failed to load generated certificate..."` - File I/O after generation
  - `"Requestor '<nick>' not found..."` - Requestor disconnected during request
- **Receiver:** Client must be online to receive the certificate bundle

**`cryptserv.default [args]`**
- Shows help message and available commands
- **Syntax:** `AI <token> cryptserv help` or `AI <token> cryptserv` (unknown command)
- **Returns:** Quick reference (e.g., `"CryptServ commands: REQUEST <target>"`)
- **Args:** Optional (any args trigger fallback)

#### File Structure

```
<PROJECT_ROOT>/
├── certs/                      # Certificate storage (created automatically)
│   ├── #channel/
│   │   ├── private.pem         # RSA private key (2048+ bits)
│   │   └── public.pem          # RSA public key
│   └── alice:bob/
│       ├── private.pem
│       └── public.pem
├── scripts/
│   └── gencert.sh              # Key generation script (must exist & be executable)
└── data/
    └── cryptserv_data.json     # Metadata file (created by service)
```

#### Data Format

**`cryptserv_data.json`**
```json
{
  "issued_certs": {
    "#general": {
      "issued_at": 1704067200.5,
      "private_path": "certs/#general/private.pem",
      "public_path": "certs/#general/public.pem"
    },
    "alice:bob": {
      "issued_at": 1704067300.5,
      "private_path": "certs/alice:bob/private.pem",
      "public_path": "certs/alice:bob/public.pem"
    }
  }
}
```

- **issued_at**: Unix timestamp (float) when certificate was generated
- **private_path**: Relative path to private key from PROJECT_ROOT
- **public_path**: Relative path to public key from PROJECT_ROOT

#### Certificate Format

Certificates are PEM-encoded RSA keys:

**Private Key Example**
```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA...
...
-----END RSA PRIVATE KEY-----
```

**Public Key Example**
```
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...
...
-----END PUBLIC KEY-----
```

#### Protocol Details

**Request Flow:**
1. Client sends: `AI <token> cryptserv request #channel`
2. CryptServ checks if certificate exists in issued_certs metadata
3. If exists: Loads keys from disk
4. If not exists: 
   - Executes `gencert.sh #channel` via `wsl bash`
   - Gencert script creates `certs/#channel/{private,public}.pem`
   - CryptServ loads newly created files
5. Stores metadata in `issued_certs` with issue timestamp
6. Persists updated issued_certs to `cryptserv_data.json`
7. Sends two encrypted PRIVMSG messages to requestor:
   - `CRYPT_PRIVATE #channel :<private_key_pem>`
   - `CRYPT_PUBLIC #channel :<public_key_pem>`

**Encryption & Transmission:**
- Private keys are sent via secure PRIVMSG (encrypted by server's DH-AES layer)
- Public keys can be broadcast (non-sensitive, but still encrypted for consistency)
- Each certificate is unique per target (channel or DM pair)
- No key reuse across targets

#### External Dependencies

- **Python stdlib:** `os`, `json`, `subprocess`, `time`, `pathlib`
- **WSL/Bash:** Required for `gencert.sh` script execution
  - Uses `wsl bash` on Windows; may need adjustment for Linux/macOS
  - Must be available in system PATH on target machine
  - Subprocess call: `wsl bash <path_to_gencert.sh> <target>`
- **System Scripts:** `scripts/gencert.sh` (must exist and be executable)
  - Expected to create `certs/<target>/{private,public}.pem` files
  - Takes target name as first argument: `gencert.sh #general` or `gencert.sh alice:bob`
  - Should handle both channel names (with #) and DM pairs (with :)
  - Exit code 0 on success, non-zero on failure
  - May output to stdout/stderr for logging
- **Server Methods:**
  - `server.send_privmsg_to_client(addr, from_nick, to_nick, message)` - Send encrypted message
  - `server.clients` dict - Access connected clients for address lookup
  - `server.log(message)` - Log service operations
  - `server.project_root_dir` - Get project root for relative paths

#### Error Handling

| Error | Cause | Resolution |
|-------|-------|-----------|
| "gencert.sh not found" | Script missing or wrong path | Create `scripts/gencert.sh` and ensure it's executable |
| "Certificate generation failed" | Script execution error | Check script permissions, bash/WSL availability, stderr output |
| "Failed to load generated certificate" | File I/O after generation | Verify certs dir permissions, disk space, gencert.sh creates files |
| "Requestor '<nick>' not found" | Client disconnected during request | Ensure requestor stays connected; retry certificate request |

#### Important Design Notes

1. **On-Demand Generation:** Certificates are generated only on first request; subsequent requests reuse existing keys (metadata-driven).
2. **Metadata Tracking:** Issue timestamps stored for audit and compliance purposes.
3. **Sensitive Key Handling:** Private keys sent only to requestor via encrypted IRC message; never logged or broadcast.
4. **WSL Dependency:** Current implementation uses `wsl bash` for script execution (Windows-specific). Platform detection needed for Linux/macOS support.
5. **Single Instance:** CryptServ acts as a centralized Certificate Authority for the entire server instance.
6. **Persistence:** All issued certificates are persistent; metadata survives server restarts.
7. **No Key Rotation:** Current implementation does not support key rotation or expiration; certificates issued once are valid indefinitely.

#### Security Considerations

- **Key Storage:** Private keys stored on disk in plain PEM format. Consider disk encryption for production.
- **Access Control:** Currently accessible to any connected IRC client. Consider adding authentication tokens or ACLs.
- **Script Injection:** `gencert.sh` argument passed directly; ensure gencert.sh validates input (e.g., reject special characters).
- **Network Exposure:** Private keys transmitted via IRC message (with DH-AES encryption). Suitable for testing; consider additional TLS layers for production.
- **File Permissions:** Ensure `certs/` directory and key files are readable only by server and owner.
- **Temp Files:** gencert.sh should use secure temp directory and clean up intermediate files.

#### Usage Examples

**Request channel certificate:**
```
/msg CryptServ request #general
```

**Request DM pair certificate:**
```
/msg CryptServ request alice:bob
```

**Check issued certificates:**
```
cat certs/
ls -la certs/#general/
```

**Retrieve certificate (subsequent request, cached):**
```
/msg CryptServ request #general  # Reuses existing keys
```

---

## Utility Services

### Curl Service

**Name:** `curl`  
**Purpose:** Perform HTTP/HTTPS requests with POST/GET methods, custom headers, and request body data. Similar to the cURL command-line tool.

#### Commands

**`curl.run [-H "Header: value"] [-d "body"] [URL]`**
- Executes an HTTP request to the specified URL
- Supports GET (default) and POST (when `-d` is present) methods
- Returns full response text with HTTP status code
- **Syntax:**
  ```
  AI <token> curl run <url>                              # Simple GET
  AI <token> curl run -H "X-Custom: value" <url>         # GET with headers
  AI <token> curl run -d "data" <url>                    # POST with body
  AI <token> curl run -H "Auth: token" -d "body" <url>   # POST with headers + body
  ```
- **Args:**
  - `-H "Header: value"` – Optional header (key-value pair separated by colon). Can be specified multiple times for multiple headers.
  - `-d "body"` – Optional request body data. When present, method defaults to POST.
  - `URL` – Required. The target HTTP/HTTPS URL. Must be a valid, accessible web address.
- **Returns:** 
  - Success: `"Success (STATUS_CODE). Response: <response_text>"`
  - Error: `"Error: <error_message>"`
- **HTTP Status Codes:**
  - 2xx (Success): Response returned
  - 3xx (Redirect): Followed automatically by `requests` library
  - 4xx (Client Error): Exception raised (e.g., 404, 401)
  - 5xx (Server Error): Exception raised
- **Errors:**
  - No URL specified: `"Error: No URL specified."`
  - Invalid URL: `"Error: InvalidURL: ..."`
  - Connection timeout (>10 seconds): `"Error: ConnectTimeout: ..."`
  - HTTP error status: `"Error: HTTPError: ..."`
  - DNS resolution failure: `"Error: ConnectionError: ..."`
  - Other exceptions: `"Error: <exception_message>"`

**`curl.default [args]`**
- Shows help message for curl service
- **Returns:** Usage instructions and available methods
- **Args:** Optional (ignored)

#### Behavior Details

**Method Selection:**
- Default method is `GET`
- If `-d` flag is present with data, method automatically changes to `POST`
- Method is never explicitly specified; it's inferred from arguments

**Header Parsing:**
- Headers are specified as `-H "Key: Value"` pairs
- Multiple headers can be provided: `-H "H1: v1" -H "H2: v2"`
- Whitespace around keys/values is trimmed
- Content-Type is NOT automatically set (user must provide if needed)

**Timeout:**
- All requests have a 10-second timeout
- If timeout exceeded, request fails with `ConnectTimeout` or `ReadTimeout` error

**Request Body:**
- Body data is sent as UTF-8 encoded bytes
- No automatic content-type handling; user must specify via `-H "Content-Type: ..."`
- Empty string data (`-d ""`) is valid and sends empty body

**URL Validation:**
- Must start with `http://` or `https://`
- Must be resolvable DNS name or valid IP address
- No URL filtering or blocklist (WARNING: potential security issue)

**Response Handling:**
- Full response text is returned (no character limit)
- HTTP status code is always included in response prefix
- Headers and status from response are NOT returned (only body text)
- No automatic decompression of compressed responses (requests library handles gzip/deflate)

#### External Dependencies

- **Python Package:** `requests` – Must be installed
  - Provides HTTP client with timeout, headers, data encoding, redirect handling
  - Installed as dependency of `csc-service` or similar
  
  ```bash
  pip install requests
  ```

#### URL Restrictions & Security Notes

⚠️ **WARNING:** Currently, there are **NO URL restrictions** or safety measures. The service can make requests to:
- Local addresses (127.0.0.1, localhost, 192.168.x.x)
- Private networks (10.0.0.0/8, 172.16.0.0/12, etc.)
- External URLs
- Localhost services running on the same machine
- Any accessible IP or hostname

**Recommended Safety Measures (Future Implementation):**
- URL whitelist/blocklist configuration
- Restriction to external URLs only (block 127.0.0.1, private ranges)
- Rate limiting to prevent abuse
- Maximum response size limits
- User authentication/authorization checks
- Logging of all requests with source client
- Proxy configuration support

**Current Usage Scenario:**
- Suitable for **internal trusted networks** where all clients are trusted
- NOT recommended for untrusted public networks
- Consider adding access control before deploying in shared environments

#### Logging

The service logs all requests to the server's log file:
```
Curl service running: POST https://ntfy.sh/topic | Headers: {'Title': 'alert'} | Data: body_text
Curl service error: ConnectTimeout('...')
```

#### Usage Examples

**Simple GET request:**
```
AI secret123 curl run https://api.github.com/zen
```

Response:
```
Success (200). Response: Design for failure.
```

**POST with notification service (ntfy.sh):**
```
AI secret123 curl run -H "Title: Alert" -d "Server down" https://ntfy.sh/myalerts
```

**Fetch JSON API with authentication:**
```
AI secret123 curl run -H "Authorization: Bearer token123" https://api.example.com/data
```

**POST form data:**
```
AI secret123 curl run -H "Content-Type: application/x-www-form-urlencoded" -d "key=value&foo=bar" https://example.com/form
```

**Multiple headers:**
```
AI secret123 curl run -H "Authorization: Bearer xyz" -H "User-Agent: CSC-Client" https://example.com/secure
```

#### Error Examples

**URL not provided:**
```
Success: Error: No URL specified.
```

**Timeout (10 seconds exceeded):**
```
Success (N/A). Response: Error: HTTPConnectionPool(host='slow.example.com', port=443): Read timed out. (read timeout=10)
```

**Invalid hostname:**
```
Success (N/A). Response: Error: Failed to resolve 'invalid-host-12345.com' ([Errno -2] Name or service not known)
```

**HTTP 404 (Not Found):**
```
Success (N/A). Response: Error: 404 Client Error: Not Found for url: https://example.com/missing
```

---

## Service Architecture

### Base Service Class

All services inherit from `Service`:

```python
from csc_service.server.service import Service

class MyService(Service):
    def __init__(self, server_instance):
        super().__init__(server_instance)
        self.name = "myservice"
        self.init_data("myservice_data.json")
    
    def my_command(self, arg1, arg2):
        """Handles 'AI <token> myservice my_command arg1 arg2'"""
        return "result"
    
    def default(self, *args):
        """Fallback handler for unknown commands"""
        return "Help: myservice commands ..."
```

### Invocation

Services are called via IRC:
```
AI <authentication_token> <service_name> <command> [args...]
```

Example:
```
AI secret123 cryptserv request #general
AI secret123 backup list
AI secret123 curl run https://example.com
```

### Data Persistence

Services use `init_data()` and `put_data()` for persistent JSON storage:

```python
self.init_data("myservice_data.json")  # Initializes if not exists
self.put_data("key", value)             # Writes to disk
value = self.get_data("key")            # Reads from disk
```

Data files stored in: `<PROJECT_ROOT>/data/<service_name>_data.json`

---

## Testing Services

Each service should have:
1. **Unit tests** in `tests/test_<service>_service.py`
2. **Mock server instance** for isolation
3. **Temp directories** for file operations
4. **Error case coverage** (invalid input, missing dependencies)

Example test structure:
```python
import unittest
from unittest.mock import Mock
from csc_service.shared.services.myservice import MyService

class TestMyService(unittest.TestCase):
    def setUp(self):
        self.mock_server = Mock()
        self.service = MyService(self.mock_server)
    
    def test_command_success(self):
        result = self.service.my_command("arg1", "arg2")
        self.assertIn("expected", result)
    
    def test_command_error(self):
        result = self.service.my_command("bad", "input")
        self.assertIn("Error", result)
```

---

## Common Patterns

### File-Based Services

If your service operates on files:
- Use `Path` from `pathlib` for cross-platform paths
- Create directories with `mkdir(parents=True, exist_ok=True)`
- Validate paths before operations
- Handle missing files gracefully

### Subprocess-Based Services

If your service calls external programs:
- Use `subprocess.run()` with `capture_output=True, text=True`
- Catch `CalledProcessError` for non-zero exits
- Log both stdout and stderr
- Consider WSL on Windows for bash scripts
- Validate command output before using

### IRC Integration

If your service sends messages back:
- Use `server.send_privmsg_to_client(addr, from_nick, to_nick, message)`
- Find client addresses via `server.clients` dict
- Consider message length limits (IRC: max 512 bytes)
- Encrypt sensitive data via server's IRC layer

### HTTP-Based Services (Curl Service Pattern)

If your service makes HTTP requests:
- Use `requests` library for HTTP client
- Always set reasonable timeouts (10 seconds or user-configurable)
- Catch and handle specific exceptions (`requests.RequestException`, `ConnectTimeout`, `ReadTimeout`, `HTTPError`)
- Validate URLs before making requests (or document the lack of validation)
- Log all requests with method, URL, and headers
- Return full response text or structured error messages
- Consider security implications of URL filtering/blocklisting
- Document any URL restrictions or lack thereof

---

## Troubleshooting

### "Service not found" error
- Check service name spelling (case-sensitive)
- Verify service is imported and registered with server
- Check that service's `__init__` calls `super().__init__(server_instance)`

### Data persistence issues
- Check file permissions on `<PROJECT_ROOT>/data/`
- Verify JSON files are valid (test with `python -m json.tool`)
- Ensure disk space available

### External command failures
- Check command exists and is in PATH
- Verify file permissions (scripts must be executable)
- Test command manually to debug
- Check stdout/stderr logs from server

### HTTP request failures (Curl Service)
- Verify URL is valid and accessible (test with curl or browser)
- Check firewall/network connectivity to target host
- Ensure no proxy blocking (check server logs)
- For private URLs, verify network access from server machine
- Check timeout hasn't been exceeded (default 10 seconds)
- Validate header syntax (Key: Value format)
- Confirm response isn't larger than expected

---

## Version & Compatibility

- **CSC Version:** 1.0+
- **Python:** 3.8+
- **Tested Services:** backup, cryptserv, curl
- **Last Updated:** 2025
