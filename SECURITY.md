# Security policy

## Reporting

Use GitHub Security Advisories. Do not paste chat exports, tokens, or host addresses into an issue.

## Secrets

`.env.example` has empty placeholders. The demo command returns before any SDK import and before any env file is loaded.

## Private data

`raw/`, `parsed/`, `distilled/`, and `output/` are gitignored. Do not add chat exports, Drive credentials, or rclone configs.

## Demo

`python3 main.py demo` prints `demo_sample.txt` and exits. That file contains documentation addresses only.
