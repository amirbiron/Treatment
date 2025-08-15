### Summary
- Roll back to stable baseline commit 7f8f1cb (pre-problematic merges)
- Keep existing features that are stable (including the appointments button/flow)
- Apply minimal, defensive fixes to caregiver add flow to avoid runtime errors; no new functionality introduced

### Details
- Branch created from 7f8f1cb: 
- Tests: 32 passed locally
  - Added local test deps only (pytest-asyncio, pytest-benchmark). CI unit job already installs pytest-asyncio and excludes performance tests; performance job installs pytest-benchmark. Should be green.

#### Caregiver flow hardening (minimal)
- Use safe emoji access: , etc. to prevent KeyError ('home')
- Notify new caregiver only if  present
- Use  on  fields to avoid KeyError on missing 
- No change to DB logic; saving remains as in baseline to avoid additional regressions

#### Out of scope (to plan next)
- Rebuild the caregiver add wizard to include explicit Phone (required) and Email (optional, with דלג) steps
- Incrementally cherry-pick later fixes as needed

### How to proceed
- Merge this to restore stability
- Then specify commits to cherry-pick for desired features, and we will reintroduce them incrementally with tests
