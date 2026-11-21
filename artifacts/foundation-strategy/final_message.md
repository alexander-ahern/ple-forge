I've written `output/submission.zip` with all six files at the archive root, for a campus total of **$436,017** including two rigs. My own independent re-check of the geometry file found no violations, but no grader was available, so the scoring itself is untested.

**The programme**

| Pad | Use (factor of safety) | Bearing depth | Decision | Spread-only cost | Improved cost |
|---|---|---|---|---|---|
| CR-P1 | Light industrial (3.5) | 45 in | Improved spread | $226,311 | $83,614 |
| CR-P2 | Light industrial (3.5) | 45 in | Improved spread | $262,767 | $88,835 |
| CR-P3 | Light industrial (3.5) | 45 in | Spread | $32,645 | $55,867 |
| CR-P4 | Office (3.0) | 45 in | Improved spread | $56,815 | $47,178 |
| CR-P5 | Warehouse (2.5) | 42 in | Spread | $18,051 | $36,426 |
| CR-P6 | Light industrial (3.5) | 42 in | Improved spread | $193,182 | $85,694 |

Pad costs exclude rig mobilisation.

- **Why four pads are improved on two rigs:** P1, P2 and P6 sit on very soft upper soil, and each saves more than $100k with rammed aggregate piers. One rig can serve at most two pads, so those three already need two rigs. The second rig has a free slot, so P4's $9.6k saving costs no extra mobilisation. Rig 1 serves P1 and P2, rig 2 serves P4 and P6: $80,000 mobilisation and one modulus test per improved pad.
- **Frost:** the current 1981–2010 freezing index for the county station is 556 °F-days. That is above 500, so the minimum bearing depth is 42 in. The superseded 1951–1980 value was 416.
- **Bearing depth:** I kept to 42 or 45 in. The civil record requires sloped excavation below 4.0 ft, and 48 in sits exactly on that line. 48 in would save only about $1–2k per pad but could be repriced with slopes if read the other way. No excavation reaches groundwater, so there is no dewatering.
- **Governing constraint:** bearing on every pad (applied pressure is 98–100% of allowable). Settlement (up to 0.98 in against 1 in) and differential settlement (up to 0.94 of the 1/500 limit, at the 5 ft gap between F5 and the wall footing) are also close to binding.
- **Concrete:**

  | Pads | Strength | Max water-cement ratio | What sets it |
  |---|---|---|---|
  | P1, P3, P4 | 4000 psi | 0.50 | Water exposure on all three; moderate sulfate on P1 and P4 |
  | P2, P6 | 4500 psi | 0.45 | Severe sulfate (0.23% and 0.26%) |
  | P5 | 5000 psi | 0.40 | Severe freeze-thaw class (de-icing exposure) |

- **Piers:** 30 in diameter, stress ratio 10 from the FHWA manual. Replacement ratios are 0.33–0.39 and treatment depths 8–9 ft. Peak pier-top stress is 14.2 ksf against the 18 ksf maximum.
- **Shear-wall footings:** sliding factor of safety 2.30 against 2.0, counting base friction only. The load stays inside the middle third with about 7–8 in eccentricity. Uplift factor of safety is 2.98–3.17.

**Choices I made where the documents leave room**
- **Bearing pressure:** I used the lowest of three methods (Terzaghi, Meyerhof, Brinch Hansen) and kept settlement and differential-settlement targets at 98% and 97% of the limits. That is deliberately conservative and makes footings somewhat bigger than strictly needed.
- **Wall footing length:** most wall footings came out 33–36 ft long and centred on the wall, so on plan they overlap the F5, and for 36 ft also F4, footings. I left this as is because RFI-017 says to treat each unit individually and detail combined footings later, but it isn't buildable as drawn.
- **Steel ratio:** I reported the larger of 0.0018 and the flexural requirement measured on effective depth. This prices slightly more steel than measuring on the full thickness would.

**Files in `output/submission.zip`:**
- `foundation_geometry.json`
- `ground_improvement_plan.json`
- `foundation_schedule.xlsx`
- `foundation_feasibility_matrix.md`
- `constraint_register.xlsx`
- `design_basis.md`

The register has 93 rows, substantive requirements first. Cancelled and superseded documents appear only in the last eight rows, each marked "set aside". The design basis opens with the required JSON block, followed by the narrative.

## Delivered files (deterministic check)

- `/filesystem/dc_structural__foundation_strategy__blind/output/submission.zip` — **ok**, 36.8 kB — 6 entries
- `/filesystem/dc_structural__foundation_strategy__blind` — **ok** — 50 files