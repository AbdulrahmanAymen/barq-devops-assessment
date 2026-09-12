# AI Usage Log

AI (Claude) was used throughout this assessment, with its role varying by task type:

- **Infrastructure troubleshooting (Docker Compose, NGINX, PostgreSQL, Redis):** I led the
  investigation and decision-making myself. AI was used as a reference to explain concepts
  and to help me read configuration files side by side, but I identified the
  specific mismatches, chose the fixes, and verified every result myself.

- **Python scripting (`analyze_logs.py`, `validate.py`, `failure_test.py`):** AI assistance
  was here — it drafted the initial structure and code for these scripts, since this
  was less familiar territory for me than the infrastructure work. I ran every script myself,
  reviewed the output line by line, and caught and fixed at least one real bug the AI
  introduced (a missing `except` clause in `validate.py` that caused a `SyntaxError`) before
  accepting the code as correct.

In both cases, nothing was applied blindly — every fix and every script was verified against
real command output before being considered done.

| Tool | Purpose | Files Affected | Verification |
|---|---|---|---|
| Claude | Helped write `analyze_logs.py` to parse the three historical log files and answer the 10 log-analysis questions | log_analysis.md | Ran every script myself and copied real terminal output into the final document — no numbers were invented |
| Claude | Wrote the initial version of `validate.py`, including a bug (a missing `except` clause) that I caught by running it and getting a real Python error | validate.py | Ran the script myself, got a real error, and asked for a fix rather than accepting the first version silently |
| Claude | Wrote the initial version of `failure_test.py`'s phased structure (baseline → induce failure → measure degraded traffic → restore → verify recovery) | failure_test.py | Ran the script myself; verified the 10/10 success/fail split during the outage matched the expected behavior of `proxy_next_upstream off` in nginx.conf, rather than accepting the code without understanding why that specific ratio was expected |
| Claude | Drafted `backup.sh` / `restore.sh` using `pg_dump`/`psql` inside the running container | backup.sh, restore.sh | Ran a full backup → write new record → restore → verify cycle manually before considering the scripts complete |

## Key principle followed throughout
For infrastructure fixes, I did the diagnosis and decision-making myself, using AI mainly to
confirm my understanding of specific technical concepts. For Python scripting, I relied on AI
more heavily to produce working code, but never accepted a script as correct without running
it myself and checking the actual output — including catching a real bug in AI-generated code
during `validate.py`'s development.
