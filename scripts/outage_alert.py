"""Alert James about a scheduled workflow's problem, less and less often.

Run by .github/workflows/outage-alert.yml at the end of a scheduled run. GitHub
emails James for every failed run, so the monitored jobs never fail the run
(job-level continue-on-error); this script decides whether this run should
alert, and the workflow's alert job fails, named with the headline, only then.

What is failing comes from FAILING/HEADLINE/REPORT (the hosted health check
passes its own), plus any job in this run that failed: its failed step and the
error line from its log, so the email says why, not just that it failed.

One open issue per TITLE tracks the problem. Alerts go out when it starts, then
GAPS apart (the last gap repeats), at once when something new fails, and once
more as an all-clear when it recovers. The issue body keeps the state in a
first-line marker: <!-- failing: a,b; alerts: N; last: EPOCH -->.
"""
import json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime

GAPS = (1800, 3600, 7200, 18000, 43200, 86400)  # seconds between alerts
SLACK = 300  # scheduled runs drift by a few minutes
UPSTREAM_DOWN = re.compile(r"HTTP 5\d\d|\b50[234]\b|timed? ?out|Connection (reset|refused|aborted)|"
                           r"Temporary failure in name resolution|RemoteDisconnected", re.I)
ERROR_WORDS = re.compile(r"error|exception|fail|HTTP \d{3}|refused|denied|not found|missing|invalid", re.I)
MARKER = re.compile(r"^<!-- failing: (.*?); alerts: (\d+); last: (\d+) -->")


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def job_log(repo, job_id):
    """A finished job's plain-text log. Not through gh, which refuses output with color codes."""
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs")
    # Unredirected, so the token is not sent on to the log storage URL GitHub redirects to.
    request.add_unredirected_header("Authorization", f"Bearer {os.environ['GH_TOKEN']}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def error_line(log):
    """The line that says why a job failed: its error annotation, else the failed step's error output."""
    lines = [re.sub(r"\x1b\[[0-9;]*m", "", re.sub(r"^\ufeff?\S+Z ", "", line)).strip() for line in log.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith("##[error]"):
            message = line.removeprefix("##[error]")
            if not message.startswith("Process completed with exit code"):
                return message
            start = max((j for j in range(i) if lines[j] == "##[endgroup]"), default=-1) + 1
            output = [x for x in lines[start:i] if x and not x.startswith(("##[", "[command]", "+ "))]
            # stdout and stderr interleave out of order, so prefer a line that reads as an error.
            errors = [x for x in output if ERROR_WORDS.search(x)]
            return (errors or output or [message])[-1]
    return "no error line in the log"


def failed_jobs(repo, run_id, attempt, workflow):
    """(key, headline) for each job in this run that failed, with its failed step and error line."""
    jobs = json.loads(gh("api", f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"))["jobs"]
    found = []
    for job in jobs:
        steps = [s["name"] for s in job.get("steps") or [] if s.get("conclusion") == "failure"]
        if job.get("conclusion") != "failure" and not steps:
            continue
        try:
            why = error_line(job_log(repo, job["id"]))
        except OSError as e:
            why = f"log unavailable ({e})"
        why = " ".join(why.split())[:160]
        hint = "; looks like the government site is down, not our code" if UPSTREAM_DOWN.search(why) else ""
        step = f' at "{steps[0]}"' if steps else ""
        found.append((f"job:{job['name']}", f"{workflow} failed{step}: {why}{hint}"))
    return found


def lasted(created, now):
    minutes = int(now - datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()) // 60
    return f"{minutes} min" if minutes < 90 else f"{(minutes + 30) // 60} h"


def decide(issue, failing, now):
    """(alert kind or None, alerts, last) for this run; kind is new, reminder or clear."""
    marker = MARKER.match((issue or {}).get("body") or "")
    before = set(filter(None, marker.group(1).split(","))) if marker else set()
    alerts, last = (int(marker.group(2)), int(marker.group(3))) if marker else (0, 0)
    if not failing:
        return ("clear" if issue else None), alerts, last
    if not issue or set(failing) - before:
        return "new", 1, now
    if now - last >= GAPS[min(max(alerts - 1, 0), len(GAPS) - 1)] - SLACK:
        return "reminder", alerts + 1, now
    return None, alerts, last


def main():
    env = os.environ
    repo, title, now = env["GITHUB_REPOSITORY"], env["TITLE"], int(time.time())
    run_url = f"{env['GITHUB_SERVER_URL']}/{repo}/actions/runs/{env['RUN_ID']}"
    failing = [s for s in env.get("FAILING", "").split(",") if s]
    headlines = [env["HEADLINE"]] if env.get("HEADLINE") else []
    for key, line in failed_jobs(repo, env["RUN_ID"], env.get("RUN_ATTEMPT", "1"), env["WORKFLOW"]):
        failing.append(key)
        headlines.append(line)
    headline = "; ".join(headlines)
    issues = json.loads(gh("issue", "list", "--state", "open", "--search", f'in:title "{title}"',
                           "--json", "number,title,body,createdAt"))
    issue = next((i for i in issues if i["title"].startswith(title)), None)
    kind, alerts, last = decide(issue, failing, now)
    alert = None
    if failing:
        body = (f"<!-- failing: {','.join(failing)}; alerts: {alerts}; last: {last} -->\n"
                f"**{headline}**\n\n{env.get('REPORT', '')}\n\nLatest run: {run_url}\n")
        if issue:
            gh("issue", "edit", str(issue["number"]), "--title", f"{title}: {headline}"[:250], "--body", body)
            if kind == "new":
                gh("issue", "comment", str(issue["number"]), "--body", f"Newly failing: {headline}\n\n{run_url}")
        else:
            gh("issue", "create", "--title", f"{title}: {headline}"[:250], "--body", body)
        if kind == "new":
            alert = headline
        elif kind == "reminder":
            alert = f"Still failing after {lasted(issue['createdAt'], now)}: {headline}"
    elif issue:
        gh("issue", "comment", str(issue["number"]), "--body", f"Passing again. {run_url}")
        gh("issue", "close", str(issue["number"]))
        alert = f"All clear: passing again after {lasted(issue['createdAt'], now)} ({title})"
    print(alert or "No alert this run.")
    if alert:
        with open(env["GITHUB_OUTPUT"], "a") as out:
            out.write(f"alert={' '.join(alert.split())[:300]}\n")


if __name__ == "__main__":
    sys.exit(main())
