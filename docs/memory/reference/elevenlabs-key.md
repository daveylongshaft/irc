---
slug: elevenlabs-key
name: ElevenLabs API key location
description: Pro-tier ElevenLabs key for the english/ animation framework lives at C:\Users\davey\.api_keys (outside any repo).
type: reference
status: reference
tags: [reference, api-keys, elevenlabs]
related: []
updated: 2026-05-01T00:00:00Z
---

The english/ animation framework (C:\claude\english) reads its ElevenLabs key from C:\Users\davey\.api_keys via animation_framework/voice.py::_load_dotenv().

Loader scan order: ~/.api_keys -> ~/.env -> <project>/.env (first found wins per key).

Why outside the repo: english/ is intended for public release; storing keys in home dir prevents accidental leakage. User directive: "keep it safe, store it where it wont be uploaded if the project goes public."

Tier: Pro (allows forced alignment, full feature read access). Format mp3_44100_128 is the safe default (works on Free); pcm_44100 requires Pro.

Never copy this key into a project directory or commit it. To rotate, edit C:\Users\davey\.api_keys only.
