I've written the full campus design to `submission/model.ifc`. My own checker in `/tmp/ple-forge/gen.py` passes every binding requirement for Phase 1 alone and for full build-out. It hasn't been graded: there was no oracle in this run and no IFC library in the workspace. I checked the file by hand-parsing it: every entity reference resolves, the IDs are unique and the networks payload reads back as valid JSON.

**Layout (metres, local coordinates)**
| Item | Phase | Footprint | Height / storeys |
|---|---|---|---|
| DH_P1 (data hall) | 1 | 95–170 × 19–81 (4,650 m², 9,300 m² floor area) | 8 m / 2 |
| DH_P2 (data hall) | 2 | 90–170 × 192–250 (4,640 m², 9,280 m² floor area) | 8 m / 2 |
| SUB (substation) | 1 | 186–218 × 170–202 | 5 m / 1 |
| GEN (generator yard) | 1 | 200–224 × 234–261 | 3.2 m / 1 |
| CTP (cooling plant) | 1 | 254–284 × 234–261.5 | 3.5 m / 1 |
| BRM (berm) | 1 | L-shape screening GEN and CTP to the south and west | 5 m |
| RET (stormwater) | 1 | 20–174 × 3–16 (2,002 m²) | below grade, −0.3 to 0 |

**Networks**
- **Road:** one 6 m road from a single south-frontage entrance at (180, 0), north through the corridor between the wetlands to y = 217, then east to x = 262.
- **MV power:**
  - utility point (320, 195) to SUB;
  - SUB to DH_P1 (Phase 1);
  - SUB to DH_P2 (Phase 2), stopping 0.5 m short of each building.
- **Graph:** typed utility feed, power feed and vehicle access links between the buildings, the gate and the utility point.

**Key results**
| Check | Result | Limit |
|---|---|---|
| Phase 1 cost (MV length + 0.3 × road length) | 287.9 | ≤ 314 |
| Full build-out cost | 303.9 | ≤ 473 (reference 454.7) |
| Noise at R1 / R2 | 38.2 / 38.7 dB | ≤ 42.35 dB |
| Building coverage | 13.17 % | ≤ 15.1 % |
| Stormwater area | 2,002 m² | ≥ 1,693 m² (11.8 % of impervious area) |

- **Generator screening:** the generator yard is hidden from both receptors at 1.7 m eye height.
- **Separations:** the generator yard is at least 30 m from every occupied structure (28 m required).
- **Clearances:**
  - setbacks are at least 18.5 m;
  - buildings and the road clear both wetlands by at least 9 m (8 m required);
  - every occupied or hazardous structure is within 17 m of the road (18 m required).
- **Phase separation:** no utility line runs under a building of a different phase.

**Decision for you:** the program lists the Phase 2 data hall with a count of 2. I read this as two halls in total and modelled one hall per phase, because a third hall would push coverage over 15.1 %. If the verifier expects two Phase 2 halls, the design fails.

**Close margins** (each depends on how the verifier measures):
- The generator yard and cooling plant pass the 18 m access rule by 1 m measured to their footprints. Measured from their centres instead, they would fail.
- About 4 dB of the noise margin at R2 depends on the berm being credited as blocking the cooling plant and the generator yard.

Working files (`plan.md`, `notes.md`, `calc_log.csv`, `gen.py`) are in `/tmp/ple-forge/`.

## Delivered files (deterministic check)

- `/app/files/frontier__DCBim__p6_002/submission/model.ifc` â€” **ok**, 10.8 kB â€” 166 entities