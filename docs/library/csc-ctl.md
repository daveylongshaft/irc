# `csc-ctl` Command Reference

`csc-ctl` is the primary command-line tool for managing and configuring the CSC (Client-Server-Commander) services. It allows for cross-platform control of service lifecycle, configuration, and state.

## Global Options

- `--config <file_path>`: Specify a path to the configuration file. Overrides the default `csc-service.json` and the `CSC_CONFIG_FILE` environment variable.

## Commands

### `status`

Displays the current status of services.

**Usage:**
```bash
csc-ctl status [<service>]
```

**Examples:**

- Show the status of all services:
  ```bash
  csc-ctl status
  ```

- Show the status of a specific service:
  ```bash
  csc-ctl status queue-worker
  ```

### `show`

Displays the configuration of a service.

**Usage:**
```bash
csc-ctl show <service> [<setting>]
```

**Examples:**

- Show the entire configuration for the `queue-worker` service:
  ```bash
  csc-ctl show queue-worker
  ```

- Show only the `poll_interval` for the `queue-worker` service:
  ```bash
  csc-ctl show queue-worker poll_interval
  ```

### `config`

Gets or sets a configuration value for a service.

**Usage:**
```bash
csc-ctl config <service> <setting> [<value>]
```

**Examples:**

- Get the current `poll_interval` for the `queue-worker`:
  ```bash
  csc-ctl config queue-worker poll_interval
  ```

- Set the `poll_interval` for the `queue-worker` to 300 seconds:
  ```bash
  csc-ctl config queue-worker poll_interval 300
  ```

- Enable the `test-runner` service:
  ```bash
  csc-ctl config test-runner enabled true
  ```

### `dump`

Exports service configurations to stdout in JSON format.

**Usage:**
```bash
csc-ctl dump [<service>]
```

**Examples:**

- Dump the entire service configuration:
  ```bash
  csc-ctl dump
  ```

- Dump the configuration for the `queue-worker` service:
  ```bash
  csc-ctl dump queue-worker
  ```

- Save a backup of the entire configuration:
  ```bash
  csc-ctl dump > csc-service-backup.json
  ```

### `import`

Imports service configurations from stdin.

**Usage:**
```bash
csc-ctl import [<service>]
```

**Examples:**

- Import a full configuration backup:
  ```bash
  csc-ctl import < csc-service-backup.json
  ```

- Import a configuration for a single service:
  ```bash
  csc-ctl import queue-worker < queue-worker-config.json
  ```

### `restart`

Restarts a service.

**Usage:**
```bash
csc-ctl restart <service> [--force]
```

**Examples:**

- Gracefully restart the `queue-worker` service:
  ```bash
  csc-ctl restart queue-worker
  ```

- Forcefully restart the `csc-server`:
  ```bash
  csc-ctl restart csc-server --force
  ```

### `install`

Installs a service.

**Usage:**
```bash
csc-ctl install <service>
```

**Examples:**

- Install the `queue-worker` service:
  ```bash
  csc-ctl install queue-worker
  ```

### `remove`

Removes a service.

**Usage:**
```bash
csc-ctl remove <service>
```

**Examples:**

- Remove the `queue-worker` service:
  ```bash
  csc-ctl remove queue-worker
  ```

### `cycle`

Triggers a one-time processing cycle for a service.

**Usage:**
```bash
csc-ctl cycle <service>
```

**Examples:**

- Run the `queue-worker` cycle immediately:
  ```bash
  csc-ctl cycle queue-worker
  ```
