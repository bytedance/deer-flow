# SOP skeleton (generic shape — extraction seam)

This is the domain-agnostic shape the blocking-IO skill instantiates. It exists
so a second detector/gate domain can reuse the flow without copying it. Do not
add machinery for that until a second domain actually appears (YAGNI).

A domain provides:
- a **static detector** that can scan a diff (or the whole tree) and emit
  located candidates,
- a **CI gate** that fails when the bad pattern executes,
- a **test location** for guard tests,
- **good-test rules** for that gate,
- a **teeth definition** (how to make the gate fire on purpose).

Steps:
1. **Scope (deterministic):** intersect the diff's added lines with the
   detector's findings → candidates this change introduced/touched. (Or, in
   triage mode, take the full finding list ordered by priority.)
2. **Judge (router):** per candidate — guard existing fix / fix + guard /
   no-action / rule (the gate cannot see the primitive).
3. **Fix + re-scope (fixes only):** apply the fix, re-run the detector; the
   fixed candidate must vanish from the findings (match by a stable key, not
   line numbers). Pattern-level feedback in seconds — complements, never
   replaces, step 5.
4. **Generate:** draft or extend a guard test per the good-test rules, driving
   the specific branch.
5. **Verify teeth:** make the bad pattern happen → gate must fail; restore →
   gate must pass. A pattern that stays green while genuinely bad is the
   "rule" signal, not a coverage success.
6. **Deliver:** commit the verified guard test; any gate-rule change ships in
   its own commit with the fails-to-fail evidence attached.

To add a domain: supply a new fill doc (like `good-anchor-rules.md`) + detector,
and promote this file into a parent skill the instances point at.
