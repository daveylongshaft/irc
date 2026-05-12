---
slug: haven-script-server
name: Haven Script Server (Eggdrop infrastructure)
description: Pre-built eggdrop binaries, python.so, and deployment scripts at /var/www/script-server/ on haven.
type: reference
status: reference
tags: [reference, haven, eggdrop, deployment]
related: [csc-bot-package, server-topology]
updated: 2026-05-08T00:00:00Z
---

Location: /var/www/script-server/ on haven (107.173.223.138 / haven.facingaddictionwithhope.com)
Web URL: https://haven.facingaddictionwithhope.com:9444 (self-signed, requires curl -k)

Key files:
- eggdrop-static -- Statically-linked binary (use this -- no patching needed)
- python.so -- Compiled Python module for Eggdrop
- setup.sh -- One-time bot registration and PKI enrollment
- bot-loader.sh / bot-loader.py -- Bot launchers
- verify_manifest.py -- Download/verify manifest
- rehash-handler.tcl -- .rehash command (updates scripts without restart)
- eggdrop.conf.template -- Bot config template
- manifest_gen.py -- Generate manifest.json
- bot-registry.json -- Registry of deployed bots

Per-bot deploy flow:
1. Each bot has a dir at /var/www/script-server/bots/<botnick>/
2. Drop scripts/configs in, run `python3 manifest_gen.py <botnick>` to regenerate manifest.json with sha256 checksums
3. Client enrolls: `curl -k <URL>/setup.sh | bash -s <botnick> [<irc:port>]`
   - Generates RSA key + CSR, POSTs to /certs/request, gets cert + manifest
   - verify_manifest.py downloads files into ~/botnet/<botnick>/
4. Launch: `~/botnet/<botnick>/<botnick> &`

CSC integration: irc/packages/csc-eggdrop/haven-template/ in csc repo. Run `stage-bot.sh <botnick>` ON haven to populate bot dir with CSC dispatcher + conf, then regenerate manifest.
