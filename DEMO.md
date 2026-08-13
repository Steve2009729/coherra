# Coherra — Live Demo Script

**Runtime: ~3 minutes.  Reset between runs: `python -m coherra.seed --demo`**

---

## Setup (run once before the demo)

```bash
# Install (editable, from the repo root)
pip install -e .

# Load the demo dataset — Alex the coding assistant's memory after months of use
python -m coherra.seed --demo
```

---

## The Demo

### Step 1 — "Here's an AI assistant's memory after months of use"

```bash
coherra scan
```

> An AI coding assistant has been storing facts about its user since January.
> It called the same concept by slightly different names at different times.
> Here's what that looks like after a full audit.

**Expected output:** health score around 55–65/100, 7 issues flagged:
- 2 contradictions (editor wars, job title drift)
- 2 duplicates (project name, team lead stored twice)
- 3 stale facts (Python version, old deadline, old test framework)

---

### Step 2 — "Two things directly contradict each other"

```bash
coherra issues
```

> The issues are grouped by severity.
> The contradictions are the most interesting: the assistant has two beliefs
> that cannot both be true.  VSCode vs Vim.  Senior Engineer vs Staff Engineer.
> Someone got promoted and the old fact was never cleaned up.

---

### Step 3 — "Let's resolve one live"

```bash
# Fix the editor contradiction (preference/preferred_editor vs preference/editor)
coherra fix f77c5f54bd
```

> Coherra shows both conflicting values side by side and asks which to keep.
> Type `a` to keep the newer "Vim" preference (preferred_editor) and archive the
> stale "VSCode" entry (editor).
> Every choice is logged permanently — Coherra never silently discards data.

```
  A  preference/preferred_editor = 'Vim'
  B  preference/editor           = 'VSCode'

  Choice: a
```

Repeat for the job title contradiction — keep the newer Staff Engineer entry:

```bash
# Fix the job title contradiction (people/alex_job_title vs people/alex_role)
coherra fix 095fe4d5c6
```

```
  A  people/alex_job_title = 'Staff Engineer'
  B  people/alex_role      = 'Senior Engineer'

  Choice: a
```

---

### Step 4 — "Clear the rest automatically"

```bash
coherra fix --all
```

> Duplicates and stale facts are safe to auto-resolve.
> Coherra merges the duplicate project names, merges the duplicate team lead entries,
> and archives the three outdated facts.
> Contradictions were skipped — those always need a human decision.

**Expected output:** 5 repairs applied, 0 failures.

---

### Step 5 — "Health score: 100"

```bash
coherra scan
```

> Seven issues.  Zero issues.  100/100.
> The memory is clean.

**Expected output:** `Health: ████████████████████ 100/100  ✓  No issues.`

```bash
coherra health
```

> One-line summary: HEALTHY (100/100), 7 entities, 0 issues.

---

### Step 6 — "And every single change is permanently logged — right here"

```bash
python - <<'EOF'
from coherra.client import open_client
client = open_client()
events = client.read_events(limit=10)
repairs = [e for e in events if
           isinstance(e.get("acted"), dict) and
           e["acted"].get("kind") == "coherra_repair"]
print(f"Found {len(repairs)} coherra_repair journal entries:\n")
for r in repairs:
    b = r["acted"]["body"]
    print(f"  [{b['severity']:12s}]  {b['action_taken']:12s}  issue:{b['issue_id']}  ts:{b['timestamp']}")
EOF
```

> Inside Sibyl Memory's own journal tier.  Append-only.  Never overwritten.
> Every repair Coherra has ever made is right here, forever,
> stored in the same memory system it's auditing.

---

## Reset

```bash
python -m coherra.seed --demo
```

Wipes all demo entities and reloads the drifted dataset.  Takes ~2 seconds.
