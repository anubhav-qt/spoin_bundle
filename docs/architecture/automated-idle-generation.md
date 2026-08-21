# Automated Incomplete Topic Scanning & Idle Generation

> Architecture and operational guide for automated, quota-aware corpus expansion.
> Implemented: 2026-08-22.

---

## 1. Overview & Problem

In production, user-initiated topic subscriptions create `GenerationJob` rows claimed by the worker. However, background corpus expansion (e.g. newly seeded topics or partially completed subtopic tiers) requires a proactive mechanism to:
1. Scan `spoin_db` for unstarted or under-filled topics.
2. Pace daily LLM quota smoothly across the day.
3. Automatically run when web server or developer machine CPU is idle (e.g. $< 15\%$ utilization for 15 minutes).

---

## 2. Incomplete Topic Identification & Prioritization

The scanner ([`spoin.scan_and_generate`](../../apps/api/src/spoin/scan_and_generate.py)) queries `spoin_db` with the following rules:

### Conditions for Incomplete Status
1. **Unstarted Topics:** `curriculum_generated_at IS NULL`.
2. **Under-filled Subtopics:** Active persisted cards in subtopics are strictly less than `target_cards`.

### Prioritization Hierarchy
1. **Real User Interest:** Topics with real user subscribers (`subscriber_count DESC`).
2. **Seeded Topics:** Core curricular topics (`is_seeded DESC`).
3. **Completion Deficit:** Topics with the lowest completion percentage first (`completion_pct ASC`).

---

## 3. CPU Idle Monitoring Architecture

The idle daemon ([`scripts/idle_generation_runner.py`](../../scripts/idle_generation_runner.py)) operates as a lightweight daemon:
- **Sampling:** Polls system CPU load using `psutil.cpu_percent()` every 30 seconds (reads `/proc/stat` and `/proc/loadavg` on Linux, Performance Counters on Windows).
- **Idle Threshold:** If CPU load stays $\le 15.0\%$ continuously for 15 minutes (900 seconds), it triggers a single topic generation pass (`limit=1`).
- **Active Reset:** If CPU load spikes above 15%, the consecutive idle timer resets to 0.
- **Cooldown Window:** Enforces a 30-minute cooldown after each generation pass to prevent consecutive burst calls and protect RPM sliding windows.

---

## 4. Production Deployment Methods

### A. Linux Crontab
```bash
*/15 * * * * cd /opt/spoin/apps/api && PYTHONPATH=src SPOIN_DATABASE_URL="postgresql+asyncpg://spoin:spoin@localhost:5432/spoin_db" python3 -m spoin.scan_and_generate --limit 1 >> /var/log/spoin-scan.log 2>&1
```

### B. Linux `systemd` Service & Timer
Files located in [`scripts/systemd/`](../../scripts/systemd/):
- `spoin-scan.service`: Oneshot execution of `spoin.scan_and_generate --limit 1`.
- `spoin-scan.timer`: Triggers every 15 minutes with jitter.

```bash
sudo cp scripts/systemd/spoin-scan.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spoin-scan.timer
```

### C. Continuous Linux / Windows Background Daemon
```bash
# Linux
nohup ./scripts/start_idle_runner.sh 15 15.0 1 > /var/log/spoin-idle.log 2>&1 &

# Windows PowerShell
.\scripts\start_idle_runner.ps1 -Background
```

### D. Windows Task Scheduler
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_windows_task.ps1
```
