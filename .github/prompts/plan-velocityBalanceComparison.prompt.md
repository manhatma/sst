## Plan: Add Velocity Balance Comparison to Comparison Tab

The "Travel hist. comp." tab currently shows a full-width travel histogram comparison (+ FFT below). We split it into a two-column 50/50 layout: left keeps the existing histogram+FFT, right adds a new combined velocity balance comparison diagram showing compression and rebound trendlines in a single chart. Compression trendlines sit above x-axis (positive velocity), rebound below (negative velocity), with a horizontal zero-line separating them. Lines only, no scatter dots.

---

### Phase 1: New Bokeh figure — `velocity_balance_comparison_figure()`

**File:** [dashboard/app/telemetry/balance.py](dashboard/app/telemetry/balance.py)

1. Add `velocity_balance_comparison_figure(front_strokes, rear_strokes, front_max, rear_max, front_color, rear_color)`:
   - Reuses existing `_balance_data()` for both compression and rebound stroke sets
   - Negates rebound velocity & trend arrays to place them below y=0
   - Creates a Bokeh `figure` with `name='velocity_balance_comp'`, x-axis = Travel (%), y-axis = Velocity (mm/s)
   - Adds a horizontal `Span(location=0)` as the zero-line separator (compression above, rebound below)
   - Plots **4 trendlines** only (no scatter): comp\_front, comp\_rear, reb\_front, reb\_rear
   - Uses 4 named `ColumnDataSource`s (`ds_vc_f`, `ds_vc_r`, `ds_vr_f`, `ds_vr_r`)
   - Adds slope labels at trendline endpoints
2. Add `update_velocity_balance_comparison()` returning pre-computed update data for JS

---

### Phase 2: Restructure `thist_comp` layout

**File:** [dashboard/app/telemetry/session_html.py](dashboard/app/telemetry/session_html.py)

3. Import `velocity_balance_comparison_figure` from `balance.py`
4. In `create_cache()`, inside the `if suspension_count == 2:` block:
   - Create the new figure with all compression + rebound strokes
   - Change `p_thist_comp` from `column([hist, fft])` to `row([column([hist, fft]), vel_balance_comp])`
   - No new DB column needed — figure embedded in existing `thist_comp` Bokeh layout

---

### Phase 3: JavaScript update

**File:** [dashboard/frontend/src/models/Global.js](dashboard/frontend/src/models/Global.js)

5. In `process_double_json()`: pass `u.balance` to `SST.update.thist_comp()` as additional arg
6. In `SST.update.thist_comp()`:
   - Update children access: `p.children[0]` → `p.children[0].children[0]` (hist), `p.children[0].children[1]` (fft)
   - Add update for `p.children[1]` (velocity balance): update 4 data sources, negate rebound values in JS

---

### Phase 4: API / CSS

7. **No API changes** — `/filter` already returns `balance.compression` and `balance.rebound`
8. **CSS** — verify `.thist-comp` layout; Bokeh `row()` handles the 50/50 split internally, but may need adjustment on mobile

---

### Relevant files
- [dashboard/app/telemetry/balance.py](dashboard/app/telemetry/balance.py) — new figure function, reuse `_balance_data()`, `get_valid_color()`
- [dashboard/app/telemetry/session_html.py](dashboard/app/telemetry/session_html.py) — restructure `thist_comp` from column → row with two children
- [dashboard/frontend/src/models/Global.js](dashboard/frontend/src/models/Global.js) — update thist_comp JS handler for new nested layout + balance data sources
- [dashboard/app/static/layout-double.css](dashboard/app/static/layout-double.css) — verify/adjust if needed

### Verification
1. Regenerate cache for a dual-suspension session (old caches break due to layout change)
2. Verify "Travel hist. comp." tab shows two 50% columns
3. Left: unchanged histogram + FFT; Right: 4 trendlines (comp above zero, reb below)
4. Select a time range → both columns update
5. Test mobile breakpoint
6. Run `pytest dashboard/tests/`

### Decisions
- Rebound velocity negated (Q4: +travel, -velocity) per your selection
- Trendlines only (polyfit lines), no scatter dots
- No new DB column — embedded in existing `thist_comp` layout
- Old cached sessions require regeneration
